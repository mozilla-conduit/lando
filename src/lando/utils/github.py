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

    def get(self, path: str, *args, **kwargs) -> requests.Response:
        """Send a GET request to the GitHub API with given args and kwargs."""
        url = f"{self.GITHUB_BASE_URL}/{path}"
        return self.session.get(url, *args, **kwargs)

    def post(self, path: str, *args, **kwargs) -> requests.Response:
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

    def get(self, path: str, *args, **kwargs) -> dict | list:
        """Get API endpoint scoped to the repo_base_url.

        Parameters:

        path: str
            Relative path without leading `/`.

        Return:
            dist | list: decoded JSON from the response
        """
        result = self.client.get(f"{self.repo_base_url}/{path}", *args, **kwargs)
        result.raise_for_status()
        return result.json()

    def list_pull_requests(self) -> list:
        """List all pull requests in the repo."""
        return self.get("pulls")

    def get_pull_request(self, pull_number: int) -> dict:
        """Get a specific pull request from the repo."""
        return self.get(f"pulls/{pull_number}")

    def get_diff(self, url: str) -> str:
        pass


class PullRequest:
    """A class that parses data returned from the GitHub API for pull requests."""

    def __repr__(self) -> str:
        return f"Pull request #{self.number} ({self.head_repo_git_url})"

    def __init__(self, data: dict):
        self.url = data["url"]
        self.base_ref = data["base"]["ref"]  # "source" branch name
        self.base_sha = data["base"]["sha"]  # "source" branch sha
        self.base_user_login = data["base"]["user"]["login"]
        self.base_user_id = data["base"]["user"]["id"]
        self.created_at = data["created_at"]
        self.updated_at = data["updated_at"]
        self.closed_at = data["closed_at"]
        self.merged_at = data["merged_at"]
        self.diff_url = data["diff_url"]
        self.patch_url = data["patch_url"]
        self.body = data["body"]  # description
        self.is_draft = data["draft"]
        self.comments_url = data["comments_url"]
        self.commits_url = data["commits_url"]

        self.head_ref = data["head"]["ref"]  # "destination" branch name
        self.head_sha = data["head"]["sha"]
        self.head_repo_git_url = data["head"]["repo"][
            "git_url"
        ]  # e.g., git://github.com/mozilla-conduit/test-repo.git
        self.html_url = data["html_url"]
        self.id = data["id"]
        self.number = data["number"]
        self.requested_reviewers = [
            {"id": r["id"], "html_url": r["html_url"], "login": r["login"]}
            for r in data["requested_reviewers"]
        ]
        self.requested_teams = [
            {
                "id": r["id"],
                "html_url": r["html_url"],
                "name": r["name"],
                "slug": r["slug"],
                "description": r["description"],
            }
            for r in data["requested_teams"]
        ]

        self.state = data["state"]  # e.g., "open"
        self.title = data["title"]

        self.user_id = data["user"]["id"]
        self.user_html_url = data["user"]["html_url"]
        self.user_login = data["user"]["login"]
