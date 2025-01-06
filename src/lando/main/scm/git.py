import asyncio
import logging
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import ContextManager, Optional

from django.conf import settings
from simple_github import AppAuth, AppInstallationAuth

from lando.main.scm.consts import SCM_TYPE_GIT
from lando.main.scm.exceptions import SCMException

from .abstract_scm import AbstractSCM

logger = logging.getLogger(__name__)

ENV_COMMITTER_NAME = "GIT_COMMITTER_NAME"
ENV_COMMITTER_EMAIL = "GIT_COMMITTER_EMAIL"

# From RFC-3986 [0]:
#
#     userinfo    = *( unreserved / pct-encoded / sub-delims / ":" )
#
#     unreserved  = ALPHA / DIGIT / "-" / "." / "_" / "~"
#     pct-encoded   = "%" HEXDIG HEXDIG
#     sub-delims  = "!" / "$" / "&" / "'" / "(" / ")"
#                 / "*" / "+" / "," / ";" / "=
#
# [0] https://www.rfc-editor.org/rfc/rfc3986
URL_USERINFO_RE = re.compile(
    "(?P<userinfo>[-A-Za-z0-9:._~%!$&'*()*+;=]*@)", flags=re.MULTILINE
)
GITHUB_URL_RE = re.compile(
    f"https://{URL_USERINFO_RE.pattern}?github.com/(?P<owner>[-A-Za-z0-9]+)/(?P<repo>[^/]+)"
)


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
        return SCM_TYPE_GIT

    @classmethod
    def scm_name(cls):
        """Return a _human-friendly_ string identifying the supported SCM."""
        return "Git"

    def clone(self, source: str):
        """Clone a repository from a source."""
        # When cloning, self.path doesn't exist yet, so we need to use another CWD.
        self._git_run("clone", source, self.path, cwd="/")

    def push(
        self,
        push_path: str,
        push_target: Optional[str] = None,
        force_push: bool = False,
    ):
        """Push local code to the remote repository."""
        command = ["push"]

        if force_push:
            command += ["--force"]

        if match := re.match(GITHUB_URL_RE, push_path):
            # We only fetch a token if no authentication is explicitly specified in
            # the push_url.
            if not match["userinfo"]:
                logger.info(
                    "Obtaining fresh GitHub token repo",
                    extra={
                        "push_path": push_path,
                        "repo_name": match["repo"],
                        "repo_owner": match["owner"],
                    },
                )

                token = self._get_github_token(match["owner"], match["repo"])
                if token:
                    push_path = f"https://git:{token}@github.com/{match['owner']}/{match['repo']}"

        command += [push_path]

        if push_target:
            command += [f"HEAD:{push_target}"]

        self._git_run(*command, cwd=self.path)

    @staticmethod
    def _get_github_token(repo_owner: str, repo_name: str) -> Optional[str]:
        """Obtain a fresh GitHub token to psuh to the specified repo.

        This relies on GITHUB_APP_ID and GITHUB_APP_PRIVKEY to be set in the
        environment. Returns None if those are missing.

        The app with ID GITHUB_APP_ID needs to be enabled for the target repo.

        """
        app_id = settings.GITHUB_APP_ID
        app_privkey = settings.GITHUB_APP_PRIVKEY

        if not app_id or not app_privkey:
            logger.warning(
                "Missing GITHUB_APP_ID or GITHUB_APP_PRIVKEY to authenticate against GitHub",
                extra={
                    "repo_name": repo_name,
                    "repo_owner": repo_owner,
                },
            )
            return None

        app_auth = AppAuth(
            app_id,
            app_privkey,
        )
        session = AppInstallationAuth(app_auth, repo_owner, repositories=[repo_name])
        return asyncio.run(session.get_token())

    def last_commit_for_path(self, path: str) -> str:
        """Find last commit to touch a path."""
        command = ["log", "--max-count=1", "--format=%H", "--", path]
        return self._git_run(*command, cwd=self.path)

    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        """Apply the given patch to the current repository."""
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
                self._git_run(*c, cwd=self.path)

    @contextmanager
    def for_pull(self) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pulling."""
        yield self

    @contextmanager
    def for_push(self, requester_email: str) -> ContextManager:
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

    def head_ref(self) -> str:
        """Get the current revision_id"""
        return self._git_run("rev-parse", "HEAD", cwd=self.path)

    def changeset_descriptions(self) -> list[str]:
        """Retrieve the descriptions of commits in the repository."""
        command = ["log", "--format=%s", "@{u}.."]
        return self._git_run(*command, cwd=self.path).splitlines()

    def update_repo(self, pull_path: str, target_cset: Optional[str] = None) -> str:
        """Update the repository to the specified changeset.

        This method uses the Git commands to update the repository
        located at the given pull path to the specified target changeset.
        """
        branch = target_cset or self.default_branch
        self.clean_repo()
        self._git_run("pull", "--prune", pull_path, cwd=self.path)
        self._git_run("checkout", "--force", "-B", branch, cwd=self.path)
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
        self._git_run("commit", "--all", "--amend", "--no-edit", cwd=self.path)
        return [self.get_current_node()]

    def format_stack_tip(self, commit_message: str) -> Optional[list[str]]:
        """Add an autoformat commit to the top of the patch stack."""
        self._git_run("commit", "--all", "--message", commit_message, cwd=self.path)
        return [self.get_current_node()]

    def get_current_node(self) -> str:
        """Return the commit_id of the tip of the current branch."""
        return self._git_run("rev-parse", "HEAD", cwd=self.path)

    @property
    def repo_is_initialized(self) -> bool:
        """Determine whether the target repository is initialised."""
        if not Path(self.path).exists():
            return False

        try:
            self._git_run("status", cwd=self.path)
        except SCMException:
            return False

        return True

    @classmethod
    def repo_is_supported(cls, path: str) -> bool:
        """Determine wether the target repository is supported by this concrete implementation."""
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
        sanitised_command = [cls._redact_url_userinfo(a) for a in command]
        logger.info(
            "running git command",
            extra={
                "command": sanitised_command,
                "command_id": correlation_id,
                "path": cwd,
            },
        )

        result = subprocess.run(
            command, cwd=path, capture_output=True, text=True, env=cls._git_env()
        )

        if result.returncode:
            redacted_stderr = cls._redact_url_userinfo(result.stderr)
            raise SCMException(
                f"Error running git command; {sanitised_command=}, {path=}, {redacted_stderr}",
                cls._redact_url_userinfo(result.stdout),
                redacted_stderr,
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

    @staticmethod
    def _redact_url_userinfo(s: str) -> str:
        return re.sub(URL_USERINFO_RE, "[REDACTED]@", s)

    @classmethod
    def _git_env(cls):
        env = os.environ.copy()
        env.update(cls.DEFAULT_ENV)
        return env
