import copy
import io
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Self,
)

import hglib
from django.conf import settings
from typing_extensions import override

from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.commit import CommitData
from lando.main.scm.consts import SCM_TYPE_HG, MergeStrategy
from lando.main.scm.exceptions import (
    PatchConflict,
    SCMException,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.main.scm.helpers import HgPatchHelper, PatchHelper

logger = logging.getLogger(__name__)

REQUEST_USER_ENV_VAR = "AUTOLAND_REQUEST_USER"

NULL_PARENT_HASH = 40 * "0"


class HgException(SCMException):
    """
    A base exception for Mercurial error.

    It contains logic allowing more precise exceptions to be thrown based on
    matching output or error text in another exception.
    """

    SNIPPETS: list[str] = []

    hg_args: list[str]
    out: str
    err: str

    def __init__(self, hg_args: list[str], out: str, err: str, msg: str):
        self.hg_args = hg_args
        super().__init__(msg, out, err)

    @classmethod
    def from_hglib_error(cls, exc: hglib.error.CommandError) -> Self:
        """
        Convert a CommandError from hglib into a more specificy HgException.

        The conversion is done based on the `SNIPPETS` list that each of the subclasses
        of the HgExecption implement. If one of those snippets is found in either the
        `stdout` or `stderr` strings of the CommandError, the matching HgException
        subclass is returned instead.

        """
        out, err, args = (
            exc.out.decode(errors="replace"),
            exc.err.decode(errors="replace"),
            exc.args,
        )
        msg = "hg error in cmd: hg {}: {}\n{}".format(
            " ".join(str(arg) for arg in args),
            out,
            err,
        ).rstrip()

        for subclass in cls.__subclasses__():
            for snippet in subclass.SNIPPETS:
                if snippet in err or snippet in out:
                    return subclass(args, out, err, msg)

        return HgCommandError(args, out, err, msg)


class HgCommandError(HgException):
    pass


class HgTreeClosed(TreeClosed, HgException):
    """Exception when pushing failed due to a closed tree."""

    SNIPPETS = ["is CLOSED!", "treating as if CLOSED."]


class HgTreeApprovalRequired(TreeApprovalRequired, HgException):
    """Exception when pushing failed due to approval being required."""

    SNIPPETS = ["APPROVAL REQUIRED!"]


class LostPushRace(SCMLostPushRace, HgException):
    """Exception when pushing failed due to another push happening."""

    SNIPPETS = [
        "abort: push creates new remote head",
        "repository changed while pushing",
    ]


class PushTimeoutException(SCMPushTimeoutException, HgException):
    """Exception when pushing failed due to a timeout on the repo."""

    SNIPPETS = ["timed out waiting for lock held by"]


class HgmoInternalServerError(SCMInternalServerError, HgException):
    """Exception when pulling changes from the upstream repo fails."""

    SNIPPETS = [
        "abort: HTTP Error 500:",
        "abort: error: Connection timed out",
        "remote: Connection to hg.mozilla.org closed by remote host",
        "remote: could not complete push due to pushlog operational errors",
    ]


class HgPatchConflict(PatchConflict, HgException):
    """Exception when patch fails to apply due to a conflict."""

    # TODO: Parse affected files from hg output and present
    # them in a structured way.

    SNIPPETS = [
        "unresolved conflicts (see hg resolve",
        "hunk FAILED -- saving rejects to file",
        "hunks FAILED -- saving rejects to file",
    ]


class HgSCM(AbstractSCM):
    ENCODING = "utf-8"
    DEFAULT_CONFIGS = {
        "ui.username": "Otto Länd <bind-autoland@mozilla.com>",
        "ui.interactive": "False",
        "ui.merge": "internal:merge",
        "ui.ssh": (
            "ssh "
            f'-o "SendEnv {REQUEST_USER_ENV_VAR}" '
            '-o "StrictHostKeyChecking no" '
            '-o "PasswordAuthentication no" '
            f'-o "User {settings.LANDING_WORKER_USERNAME}" '
            f'-o "Port {settings.LANDING_WORKER_TARGET_SSH_PORT}"'
        ),
        "extensions.purge": "",
        "extensions.strip": "",
        "extensions.rebase": "",
        "extensions.set_landing_system": settings.BASE_DIR
        / "api/legacy/hgext/set_landing_system.py",
    }

    config: dict

    hg_repo: hglib.client.hgclient

    def __init__(self, path: str, config: dict | None = None, **kwargs):
        self.config = copy.copy(self.DEFAULT_CONFIGS)

        if config:
            self.config.update(config)

        super().__init__(path)

    @classmethod
    @override
    def scm_type(cls):  # noqa: ANN206
        """Return a string identifying the supported SCM."""
        return SCM_TYPE_HG

    @classmethod
    @override
    def scm_name(cls) -> str:
        """Return a _human-friendly_ string identifying the supported SCM."""
        return "Mercurial"

    @override
    def push(
        self,
        push_path: str,
        push_target: str | None = None,
        force_push: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        """Push local code to the remote repository."""
        if not os.getenv(REQUEST_USER_ENV_VAR):
            raise ValueError(f"{REQUEST_USER_ENV_VAR} not set while attempting to push")

        extra_args = []

        if force_push:
            extra_args.append("-f")

        if not push_target:
            self.run_hg(["push", "-r", "tip", push_path] + extra_args)
        else:
            self.run_hg_cmds(
                [
                    ["bookmark", push_target],
                    ["push", "-B", push_target, push_path] + extra_args,
                ]
            )

    def last_commit_for_path(self, path: str) -> str:
        """Find last commit to touch a path."""
        return self.run_hg(
            [
                "log",
                "--cwd",
                self.path,
                "--template",
                "{node}",
                "-l",
                "1",
                path,
            ]
        ).decode()

    @override
    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        """Apply the given patch to the current repository."""
        # Import the diff to apply the changes then commit separately to
        # ensure correct parsing of the commit message.
        f_msg = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+", suffix="msg")
        f_diff = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+", suffix="diff")
        with f_msg, f_diff:
            f_msg.write(commit_description)
            f_msg.flush()
            f_diff.write(diff)
            f_diff.flush()

            similarity_args = ["-s", "95"]

            # TODO: Using `hg import` here is less than ideal because
            # it does not use a 3-way merge. It would be better
            # to use `hg import --exact` then `hg rebase`, however we
            # aren't guaranteed to have the patche's parent changeset
            # in the local repo.
            # Also, Apply the patch, with file rename detection (similarity).
            # Using 95 as the similarity to match automv's default.
            import_cmd = ["import", "--no-commit"] + similarity_args

            try:
                self.run_hg(import_cmd + [f_diff.name])
            except HgPatchConflict as exc:
                # Try again using 'patch' instead of hg's internal patch utility.
                # But first reset to a clean working directory as hg's attempt
                # might have partially applied the patch.
                logger.info("import failed, retrying with 'patch'", exc_info=exc)
                import_cmd += ["--config", "ui.patch=patch"]
                self.clean_repo(strip_non_public_commits=False)

                # When using an external patch util mercurial won't
                # automatically handle add/remove/renames.
                try:
                    self.run_hg(import_cmd + [f_diff.name])
                    self.run_hg(["addremove"] + similarity_args)
                except HgException:
                    # Use the original exception from import with the built-in
                    # patcher since both attempts failed.
                    raise exc

            if re.match("^[0-9]+$", commit_date):
                # If the commit_date is a unix timestamp, convert to Hg internal format.
                commit_date = f"{commit_date} 0"

            self.run_hg(
                ["commit"]
                + ["--date", commit_date]
                + ["--user", commit_author]
                + ["--landing_system", "lando"]
                + ["--logfile", f_msg.name]
            )

    @override
    def apply_patch_bytes(self, patch_bytes: bytes):
        raise NotImplementedError("`apply_patch_bytes` not implemented for hg.")

    @override
    def get_patch(self, revision_id: str) -> str | None:
        """Return a complete patch for the given revision, in the git extended diff format."""
        return self.run_hg(["export", "--git", "-r", revision_id]).decode("utf-8")

    @override
    def get_patch_helper(self, revision_id: str) -> PatchHelper | None:
        """Return a PatchHelper containing the patch for the given revision."""
        patch = self.get_patch(revision_id)
        return HgPatchHelper.from_string_io(io.StringIO(patch)) if patch else None

    @override
    def process_merge_conflict(
        self,
        pull_path: str,
        revision_id: int,
        error_message: str,
    ) -> dict[str, Any]:
        """Process merge conflict information captured in a PatchConflict, and return a
        parsed structure."""
        failed_paths, rejects_paths = self._extract_error_data(error_message)

        # Find last commits to touch each failed path.
        failed_path_changesets = [
            (path, self.last_commit_for_path(path)) for path in failed_paths
        ]

        breakdown = {
            "revision_id": revision_id,
            "rejects_paths": None,
        }

        breakdown["failed_paths"] = [
            {
                "path": path,
                "url": f"{pull_path}/file/{revision}/{path}",
                "changeset_id": revision,
            }
            for (path, revision) in failed_path_changesets
        ]
        breakdown["rejects_paths"] = {}
        for path in rejects_paths:
            reject = {"path": path}
            try:
                with open(self._get_rejects_path() / self.path[1:] / path, "r") as f:
                    reject["content"] = f.read()
            except Exception as e:
                logger.exception(e)
            # Use actual path of file to store reject data, by removing
            # `.rej` extension.
            breakdown["rejects_paths"][path[:-4]] = reject
        return breakdown

    @override
    def describe_commit(self, revision_id: str = ".") -> CommitData:
        """Return Commit metadata."""
        return self._describe_revisions(revision_id)[0]

    @override
    def describe_local_changes(self, base_cset: str = "") -> list[CommitData]:
        """Return a list of the Commits only present on this branch."""
        return list(self._describe_revisions(f"{base_cset}::. and draft()"))

    def _describe_revisions(self, changeset: str = ".") -> list[CommitData]:
        """Return revision metadata for a given changeset."""
        commit_separator = self._separator()
        attribute_separator = self._separator()
        format = attribute_separator.join(
            [
                commit_separator,
                "hash:{node}",
                "parent:{p1.node}",
                "parents:{parents % '{node}'}",
                "author:{author}",
                "datetime:{date}",
                "desc:{desc}",
                "files:{files}",
            ]
        )

        commits = []

        output = self.run_hg(["log", "-r", changeset, "-T", format]).decode("utf-8")
        for commit_output in output.split(commit_separator)[1:]:
            parts = re.split(f"{attribute_separator}", commit_output)[1:]
            metadata: dict[str, Any] = dict(p.split(":", 1) for p in parts)

            metadata["parents"] = metadata["parents"].split()
            # {parents} in Mercurial is empty if the commit has a single parent.
            # We re-add it manually, but only if it is a non-null parent.
            if not metadata["parents"] and not metadata["parent"] == NULL_PARENT_HASH:
                metadata["parents"] = [metadata["parent"]]
            del metadata["parent"]

            metadata["datetime"] = datetime.fromtimestamp(
                int(metadata["datetime"].split(".")[0])
            )
            metadata["files"] = metadata["files"].split()

            commits.append(CommitData(**metadata))

        return commits

    @classmethod
    def _get_rejects_path(cls) -> Path:
        """A Path where this SCM stores rejects from a failed patch application."""
        return Path("/tmp/patch_rejects")

    @staticmethod
    def _extract_error_data(exception: str) -> tuple[list[str], list[str]]:
        """Extract rejected hunks and file paths from exception message."""
        # RE to capture .rej file paths.
        rejs_re = re.compile(
            r"^\d+ out of \d+ hunks FAILED -- saving rejects to file (.+)$",
            re.MULTILINE,
        )

        # TODO: capture reason for patch failure, e.g. deleting non-existing file, or
        # adding a pre-existing file, etc...
        rejects_paths = rejs_re.findall(exception)

        # Collect all failed paths by removing `.rej` extension.
        failed_paths = [path[:-4] for path in rejects_paths]

        return failed_paths, rejects_paths

    @contextmanager
    @override
    def for_push(self, requester_email: str):
        """Prepare the repo with the correct environment variables set for pushing.

        The request user's email address needs to be present before initializing a repo
        if the repo is to be used for pushing remotely.
        """
        os.environ[REQUEST_USER_ENV_VAR] = requester_email
        logger.debug(f"{REQUEST_USER_ENV_VAR} set to {requester_email}")
        self._open()
        try:
            yield self
        finally:
            del os.environ[REQUEST_USER_ENV_VAR]
            self._clean_and_close()

    @contextmanager
    @override
    def for_pull(self):
        """Prepare the repo without setting any custom environment variables.

        The repo's `push` method will not function inside this context manager, as the
        request user's email address will be absent (and not needed).
        """
        self._open()
        try:
            yield self
        finally:
            self._clean_and_close()

    @override
    def head_ref(self) -> str:
        """Get the current revision_id."""
        return self.run_hg(["log", "-r", ".", "-T", "{node}"]).decode("utf-8")

    @override
    def changeset_descriptions(self) -> list[str]:
        """Get a description for all the patches to be applied."""
        return (
            self.run_hg(["log", "-r", "stack()", "-T", "{desc|firstline}\n"])
            .decode("utf-8")
            .splitlines()
        )

    @override
    def update_repo(
        self,
        pull_path: str,
        target_cset: str | None = None,
        attributes_override: str = "",
    ) -> str:
        """Update the repository to the specified changeset.

        `attributes_override` is ignored.
        """
        source = pull_path
        # Obtain remote tip if not provided. We assume there is only a single head.
        if not target_cset:
            target_cset = self._get_remote_head(source)

        # Strip any lingering changes.
        self.clean_repo()

        # Pull from "upstream".
        self._update_from_upstream(source, target_cset)
        return self.head_ref()

    def _update_from_upstream(self, source, remote_rev):  # noqa: ANN001
        """Update the repository to the specified changeset (not optional)."""
        # Pull and update to remote tip.
        cmds = [
            ["pull", source],
            ["rebase", "--abort"],
            ["update", "--clean", "-r", remote_rev],
        ]

        for cmd in cmds:
            try:
                self.run_hg(cmd)
            except HgCommandError as e:
                if "abort: no rebase in progress" in e.err:
                    # there was no rebase in progress, nothing to see here
                    continue
                raise e

    def _get_remote_head(self, source: str) -> bytes:
        """Obtain remote head. We assume there is only a single head."""
        cset = self.run_hg(["identify", source, "-r", "default", "--id"]).strip()

        assert len(cset) == 12, cset
        return cset

    @override
    def format_stack_amend(self) -> list[str | None]:
        """Amend the top commit in the patch stack with changes from formatting.

        Returns a list containing a single string representing the ID of the amended commit.
        """
        try:
            # Amend the current commit, using `--no-edit` to keep the existing commit message.
            self.run_hg(["commit", "--amend", "--no-edit", "--landing_system", "lando"])

            return [self.head_ref()]
        except HgCommandError as exc:
            if "nothing changed" in exc.out:
                # If nothing changed after formatting we can just return.
                return None

            raise exc

    @override
    def format_stack_tip(self, commit_message: str) -> list[str | None]:
        """Add an autoformat commit to the top of the patch stack."""
        try:
            # Create a new commit.
            self.run_hg(
                ["commit"]
                + [
                    "--message",
                    commit_message,
                ]
                + ["--landing_system", "lando"]
            )

            return [self.head_ref()]

        except HgCommandError as exc:
            if "nothing changed" in exc.out:
                # If nothing changed after formatting we can just return.
                return

            raise exc

    @override
    def clone(self, source: str):
        """Clone a repository from a source."""
        # Use of robustcheckout here would work, but is probably not worth
        # the hassle as most of the benefits come from repeated working
        # directory creation. Since this is a one-time clone and is unlikely
        # to happen very often, we can get away with a standard clone.
        hglib.clone(
            source=source,
            dest=self.path,
            encoding=self.ENCODING,
            configs=self._config_to_list(),
        )

    @property
    @override
    def repo_is_initialized(self) -> bool:
        """Returns True if hglib is able to open the repo, otherwise returns False."""
        try:
            self._open()
        except hglib.error.ServerError:
            logger.info(f"{self} appears to be not initialized.")
            return False
        else:
            return True

    @classmethod
    @override
    def repo_is_supported(cls, path: str) -> bool:
        """Determine wether the target repository is supported by this concrete implementation"""
        # We don't rely on HGLib for this method as we don't have a configured repository yet.
        command = ["hg", "identify", path]
        returncode = subprocess.call(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return not returncode

    def run_hg_cmds(self, cmds: list[list[str]]) -> bytes:
        """Run a list of Mercurial commands, and return the last result's output."""
        last_result = b""
        for cmd in cmds:
            last_result = self.run_hg(cmd)
        return last_result

    def run_hg(self, args: list[str]) -> bytes:
        """Run a single Mercurial command, and return its output.

        A specific HgException will be raised on error."""
        try:
            return self._run_hg(args)
        except hglib.error.CommandError as exc:
            raise HgException.from_hglib_error(exc) from exc

    def _run_hg(self, args: list[str]) -> bytes:
        """Use hglib to run a Mercurial command, and return its output."""
        correlation_id = str(uuid.uuid4())
        logger.info(
            "running hg command",
            extra={
                "command": ["hg"] + [shlex.quote(str(arg)) for arg in args],
                "command_id": correlation_id,
                "path": self.path,
                "hg_pid": self.hg_repo.server.pid,
            },
        )

        out = hglib.util.BytesIO()
        err = hglib.util.BytesIO()
        out_channels = {b"o": out.write, b"e": err.write}
        ret = self.hg_repo.runcommand(
            [
                arg.encode(self.ENCODING) if isinstance(arg, str) else arg
                for arg in args
            ],
            {},
            out_channels,
        )

        out = out.getvalue()
        err = err.getvalue()
        if out:
            logger.info(
                "output from hg command",
                extra={
                    "command_id": correlation_id,
                    "path": self.path,
                    "hg_pid": self.hg_repo.server.pid,
                    "output": out.rstrip().decode(self.ENCODING, errors="replace"),
                },
            )

        if ret:
            raise hglib.error.CommandError(args, ret, out, err)

        return out

    def _open(self):
        """Initialiase hglib to run Mercurial commands."""
        self.hg_repo = hglib.open(
            self.path, encoding=self.ENCODING, configs=self._config_to_list()
        )

    def _config_to_list(self):
        """Reformat the object's config, to a list of strings suitable for hglib"""
        return ["{}={}".format(k, v) for k, v in self.config.items() if v is not None]

    def _clean_and_close(self):
        """Perform closing activities when exiting any context managers."""
        try:
            self.clean_repo()
        except Exception as e:
            logger.exception(e)
        self.hg_repo.close()

    @override
    def clean_repo(
        self,
        *,
        strip_non_public_commits: bool = True,
        attributes_override: str | None = None,
    ):
        """Clean the local working copy from all extraneous files.

        `attributes_override` is ignored.
        """
        # Reset rejects directory
        if self._get_rejects_path().is_dir():
            shutil.rmtree(self._get_rejects_path())
        self._get_rejects_path().mkdir()

        # Copy .rej files to a temporary folder.
        rejects = Path(f"{self.path}/").rglob("*.rej")
        for reject in rejects:
            os.makedirs(
                self._get_rejects_path().joinpath(reject.parents[0].as_posix()[1:]),
                exist_ok=True,
            )
            shutil.copy(
                reject, self._get_rejects_path().joinpath(reject.as_posix()[1:])
            )

        # Clean working directory.
        try:
            self.run_hg(["--quiet", "revert", "--no-backup", "--all"])
        except HgException:
            pass
        try:
            self.run_hg(["purge"])
        except HgException:
            pass

        # Strip any lingering draft changesets.
        if strip_non_public_commits:
            try:
                self.run_hg(["strip", "--no-backup", "-r", "not public()"])
            except HgException:
                pass

    @override
    def merge_onto(
        self, commit_message: str, target: str, strategy: MergeStrategy | None
    ) -> str:
        """Create a merge commit on the specified repo.

        Use the specified `MergeStrategy` if passed. Otherwise, perform
        a normal merge and fail if there are merge conflicts.

        Return the SHA of the newly created merge commit.
        """
        if strategy == MergeStrategy.OURS:
            # Create a fake `hg debugsetparent` merge.
            self.run_hg(["debugsetparents", ".", target])
        elif strategy == MergeStrategy.THEIRS:
            # Create a fake `hg debugsetparent` merge.
            self.run_hg(["debugsetparents", target, "."])
        else:
            # Without strategy, do a regular merge, and fail if there are
            # conflicts.
            self.run_hg(["merge", "-r", target])
            unresolved = self.run_hg(["resolve", "--list"]).decode("utf-8")
            unresolved_files = [
                line.split()[1]
                for line in unresolved.splitlines()
                if line.startswith("U ")
            ]
            if unresolved_files:
                raise PatchConflict(
                    f"Unresolved merge conflicts in files: {', '.join(unresolved_files)}",
                )

        self.run_hg(["commit", "-m", commit_message, "--landing_system", "lando"])

        return self.head_ref()

    @override
    def tag(self, name: str, target: str | None):
        """Create a new tag called `name` on the `target` commit.

        If `target` is `None`, use the currently checked out commit.
        """
        tag_command = ["tag", name]

        if target:
            tag_command.append(target)

        self.run_hg(tag_command)
