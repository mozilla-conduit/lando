import logging
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import ContextManager, Optional

from lando.main.scm.exceptions import SCMException

from .abstract_scm import AbstractSCM

logger = logging.getLogger(__name__)

ENV_COMMITTER_NAME = "GIT_COMMITTER_NAME"
ENV_COMMITTER_EMAIL = "GIT_COMMITTER_EMAIL"


class GitSCM(AbstractSCM):
    DEFAULT_ENV = {
        "GIT_SSH_COMMAND": (
            'ssh -o "StrictHostKeyChecking no" -o "PasswordAuthentication no"'
        ),
    }

    """An implementation of the AbstractVCS for Git, for use by the Repo and LandingWorkers."""

    default_branch: str

    def __init__(self, path: str, default_branch: str = "main"):
        self.default_branch = default_branch
        super().__init__(path)

    def clone(self, source):
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
        self._git_run(*command)

    @property
    def REJECTS_PATH(self) -> Path:
        return Path(self.path)

    def last_commit_for_path(self, repo_path: str, path: str) -> str:
        """Find last commit to touch a path.

        Args:
            repo_path (str): The path to the repository.
            path (str): The specific path within the repository.

        Returns:
            str: The commit id
        """
        command = ["log", "--max-count=1", "--format=%H", "--", path]
        result = self._git_run(*command, cwd=repo_path)
        if not result:
            raise SCMException(
                "Empty data when determining the last commit touching a find; {repo_path=}",
                result.stdout,
                result.stderr,
            )
        return result

    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        """Apply the given patch to the current repository

        Args:
            patch_buf (StringIO): The patch to apply

        Returns:
            None
        """
        self._git_apply_patch(diff, commit_description, commit_author, commit_date)

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
        return self._git_last_commit_id()

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

    def clean_repo(self, *, strip_non_public_commits=True):
        """Reset the local repository to the origin"""
        if strip_non_public_commits:
            self._git_run("reset", "--hard", "origin/HEAD")
        self._git_run("clean", "-fdx")

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

    def get_current_node(self):
        """Return the commit_id of the tip of the current branch"""
        return self._git_run("rev-parse", "HEAD").stdout.strip()

    @property
    def repo_is_initialized(self) -> bool:
        """Determine whether the target repository is initialised"""
        return Path(self.path).exists() and self._git_call("status", cwd=self.path)

    @classmethod
    def repo_is_supported(self, path: str) -> bool:
        """Determine wether the target repository is supported by this concrete implementation"""
        # This only tests a remote target without any local filesystem interaction, the CWD doesn't matter.
        return self._git_call("ls-remote", path, cwd="/tmp")

    def _git_initialize(self):
        self.refresh_from_db()

        if self.is_initialized:
            raise

        result = self._git_run("clone", self.pull_path, self.name)
        if result.returncode == 0:
            self.is_initialized = True
            self.save()
        else:
            raise Exception(f"{result.returncode}: {result.stderr}")

    def _git_pull(self):
        self._git_run("pull", "--all", "--prune")

    def _git_apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        f_msg = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        f_diff = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        with f_msg, f_diff:
            f_msg.write(commit_description)
            f_msg.flush()
            f_diff.write(diff)
            f_diff.flush()

            self._git_run("apply", f_diff.name)

            self._git_run("add", "-A")
            self._git_run(
                "commit",
                "--date",
                commit_date,
                "--author",
                commit_author,
                "--file",
                f_msg.name,
            )

    def _git_last_commit_id(self) -> str:
        return self._git_run("rev-parse", "HEAD", cwd=self.path)

    def _git_run(self, *args, cwd: Optional[str] = None, must_succeed: bool = True):
        """Run a git command and return full output.

        Parameters:

        args: list[str]
            Arguments to git

        cwd: str
            Optional path to work in, default to self.path

        Returns: CompletedProcess[str]

            An object with (at least) the following attributes: args, returncode, stdout and stderr
        """
        path = cwd or self.path
        command = ["git"] + list(args)
        logger.debug("Running " + " ".join(command) + " in " + path)
        result = subprocess.run(
            command, cwd=path, capture_output=True, text=True, env=self._git_env()
        )

        if must_succeed and result.returncode:
            raise SCMException(
                f"Error running git command; {command=}, {path=}, {result.stderr}",
                result.stdout,
                result.stderr,
            )
        return result.stdout.strip()

    @staticmethod
    def _git_call(*args, cwd: str) -> bool:
        """Run a git command and return a boolean indicating success or failure.

        Parameters:

        args: list[str]
            Arguments to git

        cwd: str
            NON OPTIONAL path to work in, default to self.path

        WARNING

        Returns: boolean

            A success indicator

        """
        command = ["git"] + list(args)
        logger.debug("Calling " + " ".join(command) + " in " + cwd)
        returncode = subprocess.call(
            command,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=GitSCM._git_env(),
        )
        return not returncode

    @classmethod
    def _git_env(cls):
        env = os.environ.copy()
        env.update(cls.DEFAULT_ENV)
        return env
