import copy
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import (
    ContextManager,
    Optional,
    Self,
)

import hglib
from django.conf import settings

from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.consts import SCM_HG
from lando.main.scm.exceptions import (
    PatchConflict,
    SCMException,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)

logger = logging.getLogger(__name__)

REQUEST_USER_ENV_VAR = "AUTOLAND_REQUEST_USER"


class HgException(SCMException):
    """
    A base exception allowing more precise exceptions to be thrown based on
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

    SNIPPETS = ["is CLOSED!"]


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
        "abort: push failed on remote",
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

    def __init__(self, path: str, config: Optional[dict] = None):
        self.config = copy.copy(self.DEFAULT_CONFIGS)

        # Somewhere to store patch headers for testing.
        self.patch_header = None

        if config:
            self.config.update(config)

        super().__init__(path)

    @classmethod
    def scm_type(cls):
        """Return a string identifying the supported SCM."""
        return SCM_HG

    @classmethod
    def scm_name(cls):
        """Return a _human-friendly_ string identifying the supported SCM."""
        return "Mercurial"

    @property
    def REJECTS_PATH(self) -> Path:
        """A Path where this SCM stores reject from a failed patch application."""
        return Path("/tmp/patch_rejects")

    def push(
        self, push_path: str, target: Optional[str] = None, force_push: bool = False
    ) -> None:
        bookmark = target
        target = push_path
        if not os.getenv(REQUEST_USER_ENV_VAR):
            raise ValueError(f"{REQUEST_USER_ENV_VAR} not set while attempting to push")

        extra_args = []

        if force_push:
            extra_args.append("-f")

        if bookmark is None:
            self.run_hg(["push", "-r", "tip", target] + extra_args)
        else:
            self.run_hg_cmds(
                [
                    ["bookmark", bookmark],
                    ["push", "-B", bookmark, target] + extra_args,
                ]
            )

    def last_commit_for_path(self, path: str) -> str:
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

    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        # Import the diff to apply the changes then commit separately to
        # ensure correct parsing of the commit message.
        f_msg = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        f_diff = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
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

            self.run_hg(
                ["commit"]
                + ["--date", commit_date]
                + ["--user", commit_author]
                + ["--landing_system", "lando"]
                + ["--logfile", f_msg.name]
            )

    @contextmanager
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
    def for_pull(self) -> ContextManager:
        """Prepare the repo without setting any custom environment variables.

        The repo's `push` method will not function inside this context manager, as the
        request user's email address will be absent (and not needed).
        """
        self._open()
        try:
            yield self
        finally:
            self._clean_and_close()

    def head_ref(self) -> str:
        return self.run_hg(["log", "-r", ".", "-T", "{node}"]).decode("utf-8")

    def changeset_descriptions(self) -> list[str]:
        """Get a description for all the patches to be applied."""
        return (
            self.run_hg(["log", "-r", "stack()", "-T", "{desc|firstline}\n"])
            .decode("utf-8")
            .splitlines()
        )

    def update_repo(self, pull_path: str, target_cset: Optional[str] = None) -> str:
        source = pull_path
        # Obtain remote tip if not provided. We assume there is only a single head.
        if not target_cset:
            target_cset = self.get_remote_head(source)

        # Strip any lingering changes.
        self.clean_repo()

        # Pull from "upstream".
        self.update_from_upstream(source, target_cset)
        return self.head_ref()

    def update_from_upstream(self, source, remote_rev):
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

    def get_remote_head(self, source: str) -> bytes:
        # Obtain remote head. We assume there is only a single head.
        cset = self.run_hg(["identify", source, "-r", "default", "--id"]).strip()

        assert len(cset) == 12, cset
        return cset

    def format_stack_amend(self) -> Optional[list[str]]:
        """Amend the top commit in the patch stack with changes from formatting.

        Returns a list containing a single string representing the ID of the amended commit.
        """
        try:
            # Amend the current commit, using `--no-edit` to keep the existing commit message.
            self.run_hg(["commit", "--amend", "--no-edit", "--landing_system", "lando"])

            return [self.get_current_node().decode("utf-8")]
        except HgCommandError as exc:
            if "nothing changed" in exc.out:
                # If nothing changed after formatting we can just return.
                return None

            raise exc

    def format_stack_tip(self, commit_message: str) -> Optional[list[str]]:
        """Add an autoformat commit to the top of the patch stack.

        Returns a list containing a single string representing the ID of the newly created commit.
        """

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

            return [self.get_current_node().decode("utf-8")]

        except HgCommandError as exc:
            if "nothing changed" in exc.out:
                # If nothing changed after formatting we can just return.
                return

            raise exc

    def get_current_node(self) -> bytes:
        """Return the currently checked out node."""
        return self.run_hg(["identify", "-r", ".", "-i"])

    def clone(self, source: str):
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
        last_result = b""
        for cmd in cmds:
            last_result = self.run_hg(cmd)
        return last_result

    def run_hg(self, args: list[str]) -> bytes:
        try:
            return self._run_hg(args)
        except hglib.error.CommandError as exc:
            raise HgException.from_hglib_error(exc) from exc

    def _run_hg(self, args: list[str]) -> bytes:
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
        self.hg_repo = hglib.open(
            self.path, encoding=self.ENCODING, configs=self._config_to_list()
        )

    def _config_to_list(self):
        return ["{}={}".format(k, v) for k, v in self.config.items() if v is not None]

    def _clean_and_close(self):
        """Perform closing activities when exiting any context managers."""
        try:
            self.clean_repo()
        except Exception as e:
            logger.exception(e)
        self.hg_repo.close()

    def clean_repo(self, *, strip_non_public_commits: bool = True):
        # Reset rejects directory
        if self.REJECTS_PATH.is_dir():
            shutil.rmtree(self.REJECTS_PATH)
        self.REJECTS_PATH.mkdir()

        # Copy .rej files to a temporary folder.
        rejects = Path(f"{self.path}/").rglob("*.rej")
        for reject in rejects:
            os.makedirs(
                self.REJECTS_PATH.joinpath(reject.parents[0].as_posix()[1:]),
                exist_ok=True,
            )
            shutil.copy(reject, self.REJECTS_PATH.joinpath(reject.as_posix()[1:]))

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
