import logging
import os
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import ContextManager, Optional

from lando.main.scm.consts import SCM_GIT
from lando.main.scm.exceptions import SCMException

from .abstract_scm import AbstractSCM

logger = logging.getLogger(__name__)

ENV_COMMITTER_NAME = "GIT_COMMITTER_NAME"
ENV_COMMITTER_EMAIL = "GIT_COMMITTER_EMAIL"


class GitSCM(AbstractSCM):
    """An implementation of the AbstractVCS for Git, for use by the Repo and LandingWorkers."""

    DEFAULT_ENV = {
        "GIT_SSH_COMMAND": (
            'ssh -o "StrictHostKeyChecking no" -o "PasswordAuthentication no"'
        ),
    }

    default_branch: str

    def __init__(self, path: str, default_branch: str = "main"):
        self.default_branch = default_branch
        super().__init__(path)

    @classmethod
    def scm_type(cls):
        """Return a string identifying the supported SCM."""
        return SCM_GIT

    @classmethod
    def scm_name(cls):
        """Return a _human-friendly_ string identifying the supported SCM."""
        return "Git"

    def clone(self, source: str):
        """Clone a repository from a source.
        Args:
            source: The source to clone the repository from.
        Returns:
            None
        """
        # When cloning, self.path doesn't exist yet, so we need to use another CWD.
        self._git_run("clone", source, self.path, cwd="/")

    def push(
        self, push_path: str, target: Optional[str] = None, force_push: bool = False
    ):
        """Push local code to the remote repository.

        Parameters:
            push_path (str): The path to the repository where changes will be pushed.
            target (Optional[str]): The target branch or reference to push to. Defaults to None.
            force_push (bool): If True, force the push even if it results in a non-fast-forward update. Defaults to False.

        Returns:
            None
        """
        command = ["push"]
        if force_push:
            command += ["--force"]
        command += [push_path]
        if target:
            command += [f"HEAD:{target}"]
        self._git_run(*command, cwd=self.path)

    def last_commit_for_path(self, path: str) -> str:
        """Find last commit to touch a path.

        Args:
            path (str): The specific path within the repository.

        Returns:
            str: The commit id
        """
        command = ["log", "--max-count=1", "--format=%H", "--", path]
        return self._git_run(*command, cwd=self.path)

    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        """Apply the given patch to the current repository

        Args:
            patch_buf (StringIO): The patch to apply

        Returns:
            None
        """
        f_msg = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        f_diff = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        with f_msg, f_diff:
            f_msg.write(commit_description)
            f_msg.flush()
            f_diff.write(diff)
            f_diff.flush()

            cmds = [
                ["apply", f_diff.name],
                ["add", "-A"],
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
                self._git_run(c, cwd=self.path)

    @contextmanager
    def for_pull(self) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pulling."""
        yield self

    @contextmanager
    def for_push(self, requester_email: str) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pushing.

        Args:
            requester_email (str)
        """
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

    def head_ref(self) -> str:
        """Get the current revision_id"""
        return self._git_run("rev-parse", "HEAD", cwd=self.path)

    def changeset_descriptions(self) -> list[str]:
        """Retrieve the descriptions of commits in the repository.

        Returns:
            list[str]: A list of first lines of changeset descriptions.
        """
        command = ["log", "--format=%s", "@{u}.."]
        return self._git_run(*command).splitlines()

    def update_repo(self, pull_path: str, target_cset: Optional[str] = None) -> str:
        """Update the repository to the specified changeset.

        This method uses the Git commands to update the repository
        located at the given pull path to the specified target changeset.

        Args:
            pull_path (str): The path to pull from.
            target_cset (str): The target changeset to update the repository to.

        Returns:
            str: The target changeset
        """
        branch = target_cset or self.default_branch
        self.clean_repo()
        self._git_run("pull", "--prune", pull_path)
        self._git_run("checkout", "--force", "-B", branch)
        return self.head_ref()

    def clean_repo(self, *, strip_non_public_commits: bool = True):
        """Reset the local repository to the origin"""
        if strip_non_public_commits:
            self._git_run(
                "reset", "--hard", f"origin/{self.default_branch}", cwd=self.path
            )
        self._git_run("clean", "-fdx", cwd=self.path)

    def format_stack_amend(self) -> Optional[list[str]]:
        """Amend the top commit in the patch stack with changes from formatting."""
        self._git_run("commit", "--all", "--amend", "--no-edit")
        return [self.get_current_node()]

    def format_stack_tip(self, commit_message: str) -> Optional[list[str]]:
        """Add an autoformat commit to the top of the patch stack.

        Return the commit hash of the autoformat commit as a `str`,
        or return `None` if autoformatting made no changes.
        """
        self._git_run("commit", "--all", "--message", commit_message)
        return [self.get_current_node()]

    def get_current_node(self) -> str:
        """Return the commit_id of the tip of the current branch"""
        return self._git_run("rev-parse", "HEAD")

    @property
    def repo_is_initialized(self) -> bool:
        """Determine whether the target repository is initialised"""
        if not Path(self.path).exists():
            return False

        try:
            self._git_run("status", cwd=self.path)
        except SCMException:
            return False

        return True

    @classmethod
    def repo_is_supported(cls, path: str) -> bool:
        """Determine wether the target repository is supported by this concrete implementation"""
        try:
            cls._git_run("ls-remote", path)
        except SCMException:
            return False

        return True

    @classmethod
    def _git_run(cls, *args, cwd: Optional[str] = None) -> str:
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
        logger.info(
            "running git command",
            extra={
                "command": command,
                "command_id": correlation_id,
                "path": cwd,
            },
        )

        result = subprocess.run(
            command, cwd=path, capture_output=True, text=True, env=cls._git_env()
        )

        if result.returncode:
            raise SCMException(
                f"Error running git command; {command=}, {path=}, {result.stderr}",
                result.stdout,
                result.stderr,
            )

        out = result.stdout.strip()

        if out:
            logger.info(
                "output from git command",
                extra={
                    "command_id": correlation_id,
                    "output": out,
                    "path": cwd,
                },
            )

        return out

    @classmethod
    def _git_env(cls):
        env = os.environ.copy()
        env.update(cls.DEFAULT_ENV)
        return env
