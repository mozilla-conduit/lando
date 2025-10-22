import asyncio
import logging

import requests
from django.conf import settings
from simple_github import AppAuth, AppInstallationAuth

from lando.main.models.repo import Repo

logger = logging.getLogger(__name__)


class GitHubAPI:
    """A simple wrapper that authenticates with and communicates with the GitHub API."""

    GITHUB_BASE_URL = "https://api.github.com"

    def __init__(self, repo: Repo):
        repo_owner = repo._github_repo_org
        repo_name = repo.git_repo_name

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._get_token(repo_owner, repo_name)}",
                "User-Agent": settings.HTTP_USER_AGENT,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    @staticmethod
    def _get_token(repo_owner: str, repo_name: str) -> str | None:
        """Obtain a fresh GitHub token to push to the specified repo.

        This relies on GITHUB_APP_ID and GITHUB_APP_PRIVKEY to be set in the
        environment. Returns None if those are missing.

        The app with ID GITHUB_APP_ID needs to be enabled for the target repo.

        """
        app_id = settings.GITHUB_APP_ID
        private_key = settings.GITHUB_APP_PRIVKEY

        if not app_id or not private_key:
            logger.warning(
                f"Missing GITHUB_APP_ID or GITHUB_APP_PRIVKEY to authenticate against GitHub repo {repo_owner}/{repo_name}",
            )
            return None

        app_auth = AppAuth(
            app_id,
            private_key,
        )
        session = AppInstallationAuth(app_auth, repo_owner, repositories=[repo_name])
        return asyncio.run(session.get_token())

    def get(self, path: str, *args, **kwargs) -> dict:
        """Send a GET request to the GitHub API with given args and kwargs."""
        url = f"{self.GITHUB_BASE_URL}/{path}"
        return self.session.get(url, *args, **kwargs)

    def post(self, path: str, *args, **kwargs) -> dict:
        """Send a POST request to the GitHub API with given args and kwargs."""
        url = f"self.GITHUB_BASE_URL/{path}"
        return self.session.post(url, *args, **kwargs)


class GitHubAPIClient:
    """A convenience client that provides various methods to interact with the GitHub API."""

    client = None

    def __init__(self, repo: Repo):
        self.client = GitHubAPI(repo)
        self.repo = repo
        self.repo_base_url = (
            f"repos/{self.repo._github_repo_org}/{self.repo.git_repo_name}"
        )

    def _get(self, path: str, *args, **kwargs) -> dict:
        result = self.client.get(path, *args, **kwargs)
        return result.json()

    def list_pull_requests(self) -> list:
        """List all pull requests in the repo."""
        return self._get(f"{self.repo_base_url}/pulls")

    def get_pull_request(self, pull_number: int) -> dict:
        """Get a specific pull request from the repo."""
        return self._get(f"{self.repo_base_url}/pulls/{pull_number}")
