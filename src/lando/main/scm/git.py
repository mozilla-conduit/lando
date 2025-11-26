import io
import logging
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from typing_extensions import override

from lando.main.scm.commit import CommitData
from lando.main.scm.consts import SCM_TYPE_GIT, MergeStrategy
from lando.main.scm.exceptions import (
    PatchConflict,
    SCMException,
    SCMInternalServerError,
    TagAlreadyPresentException,
)
from lando.main.scm.helpers import GitPatchHelper, PatchHelper
from lando.settings import LANDO_USER_EMAIL, LANDO_USER_NAME
from lando.utils.const import URL_USERINFO_RE
from lando.utils.github import GitHub

from .abstract_scm import AbstractSCM

logger = logging.getLogger(__name__)


ISO8601_TIMESTAMP_BASIC = "%Y-%m-%dT%H%M%S%Z"

ENV_COMMITTER_NAME = "GIT_COMMITTER_NAME"
ENV_COMMITTER_EMAIL = "GIT_COMMITTER_EMAIL"


class GitSCM(AbstractSCM):
    """An implementation of the AbstractVCS for Git, for use by the Repo and LandingWorkers."""

    DEFAULT_ENV = {
        "GIT_SSH_COMMAND": (
            'ssh -o "StrictHostKeyChecking no" -o "PasswordAuthentication no"'
        ),
    }

    # XXX: The `(?:while searching for)` assertion would be better as `(?!patch
    # failed)`, but this sort of negative assertion with lookahead prevents the
    # non-matching group to be captured.
    FAILED_RE = re.compile(
        r"(?:error: ((?:while searching for):\n(?:.*\n)*?))?error: patch failed: ([^:\n]+):\d+",
        re.MULTILINE,
    )

    default_branch: str

    def __init__(self, path: str, default_branch: str = "main", **kwargs):
        self.default_branch = default_branch
        super().__init__(path)

    @classmethod
    @override
    def scm_type(cls) -> str:  # noqa: ANN206
        """Return a string identifying the supported SCM."""
        return SCM_TYPE_GIT

    @classmethod
    @override
    def scm_name(cls) -> str:
        """Return a _human-friendly_ string identifying the supported SCM."""
        return "Git"

    @override
    def clone(self, source: str):
        """Clone a repository from a source."""
        # When cloning, self.path doesn't exist yet, so we need to use another CWD.
        self._git_run("clone", source, self.path, cwd="/")
        self._git_run("checkout", self.default_branch, cwd=self.path)
        self._git_setup_user()

    def _git_setup_user(self):
        """Configure the git user locally to repo_dir so as not to mess with the real user's configuration."""
        self._git_run("config", "user.name", LANDO_USER_NAME, cwd=self.path)
        self._git_run("config", "user.email", LANDO_USER_EMAIL, cwd=self.path)

    @override
    def push(
        self,
        push_path: str,
        push_target: str | None = None,
        force_push: bool = False,
        tags: list[str] | None = None,
    ):
        """Push local code to the remote repository."""

        push_command = ["push"]

        if force_push:
            push_command += ["--force"]

        if GitHub.is_supported_url(push_path):
            push_path = GitHub(push_path).authenticated_url

        push_command += [push_path]

        if not push_target:
            push_target = self.default_branch

        push_command += [f"HEAD:{push_target}"]

        # If any tags were passed, ensure they are pushed.
        if tags:
            for tag in tags:
                push_command += [f"refs/tags/{tag}"]

        self._git_run(*push_command, cwd=self.path)

    def last_commit_for_path(self, path: str) -> str:
        """Find last commit to touch a path."""
        command = ["log", "--max-count=1", "--format=%H", "--", path]
        return self._git_run(*command, cwd=self.path)

    @override
    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        """Apply the given patch to the current repository."""
        f_msg = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+", suffix=".msg")
        f_diff = tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w+", suffix=".diff"
        )
        with f_msg, f_diff:
            f_msg.write(commit_description)
            f_msg.flush()
            f_diff.write(diff)
            f_diff.flush()

            cmds = [
                ["apply", "--reject", f_diff.name],
                # Use `-f` here to include files in `.gitignore`.
                ["add", "-A", "-f"],
                [
                    "commit",
                    "--date",
                    commit_date,
                    "--author",
                    commit_author,
                    "--file",
                    f_msg.name,
                ],
            ]

            for c in cmds:
                try:
                    self._git_run(*c, cwd=self.path)
                except SCMException as exc:
                    if "error: patch" in exc.err:
                        raise PatchConflict(exc.err) from exc

                    raise exc

    @override
    def apply_patch_git(self, patch_bytes: bytes):
        """Apply the Git patch, provided as encoded bytes."""
        try:
            # Clean up existing failed `git am`.
            self._git_run("am", "--abort", cwd=self.path)
        except SCMException as exc:
            # Command will return exit code 1 if there is no failed `git am` in progress.
            # Look for the expected error message and ignore the exception.
            if "Resolve operation not in progress" not in exc.err:
                # Real error, re-raise the exception.
                raise exc

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".patch") as tmp_file:
            tmp_file.write(patch_bytes)
            tmp_file.flush()

            try:
                self._git_run("am", "--keep-cr", tmp_file.name, cwd=self.path)
            except SCMException as exc:
                try:
                    # Clean up failed `git am`.
                    self._git_run("am", "--abort", cwd=self.path)
                except SCMException:
                    pass

                # Re-raise the exception from the failed `git am`.
                raise exc

    def get_diff_from_patches(self, patches: str) -> str:
        """Apply multiple patches and return the diff output."""
        # TODO: add error handling so that if something goes wrong here,
        # a meaningful error is stored in the landing job. This would be
        # the same as what is done when actually applying the patches.
        # See bug 2000268.
        with tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w+", suffix=".patch"
        ) as patch_file:
            patch_file.write(patches)
            patch_file.flush()

            self._git_run("apply", "--reject", patch_file.name, cwd=self.path)
            self._git_run("add", "-A", "-f", cwd=self.path)
            return self._git_run(
                "diff", "--staged", "--binary", cwd=self.path, rstrip=False
            )

    @override
    def get_patch(self, revision_id: str) -> str | None:
        """Return a complete patch for the given revision, in the git extended diff format.

        Note that `_git_run` strips the output before returning it. This means
        that trailing newlines in the patch output will no be present. This is
        acceptable for our purpose, but it may not reapply cleanly (TBC).
        """
        patch = self._git_run(
            "format-patch",
            "--keep-subject",
            "--stdout",
            "-1",
            revision_id,
            cwd=self.path,
        )
        # We only return the patch if the `From` header indicates that it's the same as
        # the requested revision. This may not be the case when, e.g., `git
        # format-patch` processes a clean merge commit, in which case it returns a
        # parent of the merge.
        if not re.match(rf"^From {revision_id}", patch):
            logger.debug(
                f"Different revision ID found in patch for {revision_id}. Likely a merge, returning empty patch."
            )
            return None
        return patch

    @override
    def get_patch_helper(self, revision_id: str) -> PatchHelper | None:
        """Return a PatchHelper containing the patch for the given revision."""
        patch = self.get_patch(revision_id)
        return GitPatchHelper.from_string_io(io.StringIO(patch)) if patch else None

    @override
    def process_merge_conflict(
        self,
        pull_path: str,
        revision_id: int,
        error_message: str,
    ) -> dict[str, Any]:
        """Process merge conflict information captured in a PatchConflict, and return a
        parsed structure."""

        breakdown = {
            "failed_paths": [],
            "rejects_paths": {},
            "revision_id": revision_id,
        }

        failed_paths = self.FAILED_RE.findall(error_message)

        failed_path_commits = [
            (path, self.last_commit_for_path(path), path_error)
            for path_error, path in failed_paths
        ]

        breakdown["failed_paths"] = [
            {
                "path": path,
                "url": f"{pull_path}/tree/{revision}/{path}",
                "changeset_id": revision,
            }
            for (path, revision, _) in failed_path_commits
        ]

        for path_error, path in failed_paths:
            reject = {"path": f"{path}.rej"}

            try:
                with open(Path(self.path) / reject["path"], "r") as r:
                    reject["content"] = r.read()
            except Exception as e:
                logger.exception(e)
                reject["content"] = f"error reading rejects file {reject['path']}"

            if path_error:
                reject[
                    "content"
                ] += f"\nin addition, Git reported this error: {path_error}"

            breakdown["rejects_paths"][path] = reject

        return breakdown

    @override
    def describe_commit(self, revision_id: str = "HEAD") -> CommitData:
        """Return Commit metadata."""
        return self._describe_commits(revision_id)[0]

    @override
    def describe_local_changes(self, base_cset: str = "@{u}") -> list[CommitData]:
        """Return a list of the Commits only present on this branch.

        Use the passed target changeset as the base commit. Otherwise, use the
        configured upstream branch.
        """
        refspec = f"{base_cset}.."

        return list(reversed(self._describe_commits(refspec)))

    def _describe_commits(self, ref_spec: str = "HEAD") -> list[CommitData]:
        """Return Commit metadata for a given ref_spec (including ranges)."""
        commit_separator = self._separator()
        attribute_separator = self._separator()
        format = attribute_separator.join(
            [
                commit_separator,
                "hash:%H",
                "parents:%P",
                "author:%an <%ae>",
                "datetime:%ad",
                "desc:%B",
                "files:",
            ]
        )
        date_format = "%Y-%m-%d %H:%M:%S %z"

        output = self._git_run(
            "show",
            "--stat",
            f"--pretty=format:{format}",
            f"--date=format:{date_format}",
            ref_spec,
            cwd=self.path,
        )

        commits = []

        # As we add the separator at the beginning of the format string, the first entry
        # is always empty, so we skip it.
        for commit_output in output.split(commit_separator)[1:]:
            parts = re.split(attribute_separator, commit_output)[1:]
            metadata: dict[str, Any] = dict(p.split(":", 1) for p in parts)

            metadata["parents"] = metadata["parents"].split()
            metadata["datetime"] = datetime.strptime(metadata["datetime"], date_format)
            # Parse the --stat output, removing the last summary line.
            metadata["files"] = re.split(r"\s+\|.*\n\s+", metadata["files"].strip())[
                :-1
            ]

            commits.append(CommitData(**metadata))

        return commits

    @contextmanager
    @override
    def for_pull(self):
        """Context manager to prepare the repo with the correct environment variables set for pulling."""
        yield self

    @contextmanager
    @override
    def for_push(self, requester_email: str):
        """Context manager to prepare the repo with the correct environment variables set for pushing."""
        # We set the committer name to the requester's _email_ as this is the only piece
        # of information about the user that we are comfortable making public. Names in
        # the User objects are coming from LDAP, and may not be acceptable to use
        # publicly.
        os.environ[ENV_COMMITTER_NAME] = requester_email
        os.environ[ENV_COMMITTER_EMAIL] = requester_email
        logger.debug(
            f"{ENV_COMMITTER_EMAIL} and {ENV_COMMITTER_NAME} set to {requester_email}"
        )
        try:
            yield self
        finally:
            del os.environ[ENV_COMMITTER_NAME]
            del os.environ[ENV_COMMITTER_EMAIL]

    @override
    def head_ref(self) -> str:
        """Get the current revision_id"""
        return self._git_run("rev-parse", "HEAD", cwd=self.path)

    @override
    def changeset_descriptions(self) -> list[str]:
        """Retrieve the descriptions of commits in the repository."""
        command = ["log", "--format=%s", "@{u}.."]
        return self._git_run(*command, cwd=self.path).splitlines()

    @override
    def update_repo(
        self,
        pull_path: str,
        target_cset: str | None = None,
        attributes_override: str = "",
    ) -> str:
        """Update the repository to the specified changeset.

        This method uses the Git commands to update the repository
        located at the given pull path to the specified target changeset.

        A new work branch will be created, using the current date in its name.
        """
        if not target_cset:
            target_cset = self.default_branch

        self.clean_repo(attributes_override=attributes_override)
        # Fetch all refs at the given pull_path, and overwrite the `origin` references.
        self._git_run(
            "fetch",
            "--prune",
            pull_path,
            "+refs/heads/*:refs/remotes/origin/*",
            cwd=self.path,
        )

        remote_branch = f"origin/{target_cset}"
        if self._git_run("branch", "--list", "--remote", remote_branch, cwd=self.path):
            # If the branch exists remotely, make sure we get the up-to-date version.
            target_cset = remote_branch

        # Create a new work branch, named after the current time, to work in.
        # Ideally, we'd use the revision number, too, but it's not available to the SCM.
        # A date is good enough for now, if we need to dig into issues.
        work_branch = f"lando-{datetime.now().strftime(ISO8601_TIMESTAMP_BASIC)}"
        self._git_run(
            "checkout", "--force", "-B", work_branch, target_cset, cwd=self.path
        )
        return self.head_ref()

    @override
    def clean_repo(
        self,
        *,
        strip_non_public_commits: bool = True,
        attributes_override: str | None = None,
    ):
        """Reset the local repository to the origin"""
        if strip_non_public_commits:
            self._git_run(
                "reset", "--hard", f"origin/{self.default_branch}", cwd=self.path
            )

        # We need to differentiate between None and "" here, so we know when we were
        # explicitly given an empty string.
        if attributes_override is not None:
            # $GIT_DIR/info/attributes has the highest precedence.
            with open(f"{self._git_dir}/info/attributes", "a+") as fp:
                fp.seek(0)
                if not fp.readable() or fp.read() != attributes_override:
                    fp.seek(0)
                    fp.truncate()
                    fp.write(attributes_override)

        self._git_run("clean", "-fdx", cwd=self.path)

    @property
    def _git_dir(self):
        return self._git_run("rev-parse", "--absolute-git-dir", cwd=self.path)

    @override
    def format_stack_amend(self) -> list[str]:
        """Amend the top commit in the patch stack with changes from formatting."""
        self._git_run("commit", "--all", "--amend", "--no-edit", cwd=self.path)
        return [self.head_ref()]

    @override
    def format_stack_tip(self, commit_message: str) -> list[str]:
        """Add an autoformat commit to the top of the patch stack."""
        try:
            self._git_run("commit", "--all", "--message", commit_message, cwd=self.path)
        except SCMException as exc:
            if "nothing to commit, working tree clean" in exc.out:
                return []
            else:
                raise exc
        return [self.head_ref()]

    @property
    @override
    def repo_is_initialized(self) -> bool:
        """Determine whether the target repository is initialised."""
        if not Path(self.path).exists():
            return False

        try:
            result = self._git_run("rev-parse", "--is-inside-work-tree", cwd=self.path)
        except SCMException:
            return False

        return result.strip() == "true"

    @classmethod
    @override
    def repo_is_supported(cls, path: str) -> bool:
        """Determine wether the target repository is supported by this concrete implementation."""
        try:
            cls._git_run("ls-remote", path)
        except SCMException:
            return False

        return True

    @classmethod
    def _git_run(cls, *args, cwd: str | None = None, rstrip: bool = True) -> str:
        """Run a git command and return full output.

        Parameters:

        args: list[str]
            Arguments to git

        cwd: str
            Optional path to work in, default to '/'

        Returns:
            str: the standard output of the command
        """
        correlation_id = str(uuid.uuid4())
        path = cwd or "/"
        command = ["git"] + list(args)
        sanitised_command = [cls._redact_url_userinfo(a) for a in command]
        logger.info(
            "running git command #%s: %s",
            correlation_id,
            sanitised_command,
            extra={
                "command": sanitised_command,
                "command_id": correlation_id,
                "path": cwd,
            },
        )

        result = subprocess.run(
            command, cwd=path, capture_output=True, env=cls._git_env()
        )

        try:
            # Try decoding with utf-8 first.
            out = result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            # Try again with latin-1.
            out = result.stdout.decode("latin-1")

        out = out.lstrip()
        if rstrip:
            out = out.rstrip()

        if result.returncode:
            redacted_stderr = cls._redact_url_userinfo(result.stderr.decode("utf-8"))
            raise SCMInternalServerError(
                f"Error running git command; {sanitised_command=}, {path=}, {redacted_stderr}",
                cls._redact_url_userinfo(out),
                redacted_stderr,
            )

        if out:
            logger.info(
                "output from git command #%s: %s",
                correlation_id,
                out,
                extra={
                    "command_id": correlation_id,
                    "output": out,
                    "path": cwd,
                },
            )

        return out

    @staticmethod
    def _redact_url_userinfo(url: str) -> str:
        return re.sub(URL_USERINFO_RE, "[REDACTED]@", url)

    @classmethod
    def _git_env(cls):  # noqa: ANN206
        env = os.environ.copy()
        env.update(cls.DEFAULT_ENV)
        return env

    def get_current_branch(self) -> str:
        """Return the currently active branch."""
        return self._git_run("branch", "--show-current", cwd=self.path)

    @override
    def merge_onto(
        self, commit_message: str, target: str, strategy: MergeStrategy | None
    ) -> str:
        """Create a merge commit on the specified repo.

        Use the specified `MergeStrategy` if passed. Otherwise, perform
        a normal merge and fail if there are merge conflicts.

        Return the SHA of the newly created merge commit.
        """

        if strategy == MergeStrategy.THEIRS:
            current_branch = self.get_current_branch()
            current_sha = self.head_ref()

            timestamp = datetime.now().strftime(ISO8601_TIMESTAMP_BASIC)
            temp_branch_name = f"theirs-merge-temp-branch-{timestamp}"

            # Switch to target and merge current into it with 'ours' strategy
            self._git_run("switch", "-c", temp_branch_name, target, cwd=self.path)

            # Create merge commit that favors the target's content
            self._git_run(
                "merge",
                "--no-ff",
                # Use the `ours` strategy after moving to the target,
                # to replicate the behaviour of the deprecated `theirs`
                # merge strategy.
                "-s",
                "ours",
                "-m",
                commit_message,
                current_sha,
                cwd=self.path,
            )

            new_merge_commit = self.head_ref()

            # Move the original branch to point to the merge commit
            self._git_run(
                "branch", "-f", current_branch, new_merge_commit, cwd=self.path
            )
            self._git_run("switch", current_branch, cwd=self.path)

            return new_merge_commit

        # Set strategy args.
        strategy_args = ["--no-ff", "-s", strategy] if strategy else []

        self._git_run(
            "merge",
            "-m",
            commit_message,
            *strategy_args,
            target,
            cwd=self.path,
        )

        return self.head_ref()

    @override
    def tag(self, name: str, target: str | None):
        """Create a new tag called `name` on the `target` commit.

        If `target` is `None`, use the currently checked out commit.
        """
        tag_command = ["tag", name]

        if target:
            tag_command.append(target)

        try:
            self._git_run(*tag_command, cwd=self.path)
        except SCMInternalServerError as exc:
            if self._git_run("tag", "-l", name, cwd=self.path):
                desired_tag_target = self._git_run(
                    "rev-parse", target or "HEAD", cwd=self.path
                )
                current_tag_target = self._git_run(
                    "rev-parse", f"refs/tags/{name}", cwd=self.path
                )
                if current_tag_target != desired_tag_target:
                    raise TagAlreadyPresentException(
                        f"Tag {name} already exists, and points to different target {current_tag_target}"
                    ) from exc
                logger.warning(
                    f"Tag {name} already exists, but points to the desired target {current_tag_target}. Skipping retagging ..."
                )
                return

            # If the tag did not already exist, bubble up the exception.
            raise exc
