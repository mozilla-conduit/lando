import asyncio
import io
import logging
import math
from datetime import datetime

import requests
from django.conf import settings
from simple_github import AppAuth, AppInstallationAuth
from typing_extensions import override

# from lando.main.models.repo import Repo
from lando.main.scm.helpers import PatchHelper

logger = logging.getLogger(__name__)


class GitHubAPI:
    """A simple wrapper that authenticates with and communicates with the GitHub API."""

    GITHUB_BASE_URL = "https://api.github.com"

    def __init__(self, repo: "Repo"):
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
        url = f"{self.GITHUB_BASE_URL}/{path}"
        return self.session.post(url, *args, **kwargs)


class GitHubAPIClient:
    """A convenience client that provides various methods to interact with the GitHub API."""

    _api: GitHubAPI

    # repo: "Repo"
    repo_base_url: str

    def __init__(self, repo: "Repo"):
        self._api = GitHubAPI(repo)
        self.repo = repo
        self.repo_base_url = (
            f"repos/{self.repo._github_repo_org}/{self.repo.git_repo_name}"
        )

    def _repo_get(self, subpath: str, *args, **kwargs) -> dict | list:
        """Get API endpoint scoped to the repo_base_url.

        Parameters:

        subpath: str
            Relative path without leading `/`.

        Return:
            dist | list: decoded JSON from the response
        """
        return self._get(f"{self.repo_base_url}/{subpath}", *args, **kwargs)

    def _get(self, path: str, *args, **kwargs) -> dict | list | str | None:
        result = self._api.get(path, *args, **kwargs)
        content_type = result.headers["content-type"]
        if content_type == "application/json; charset=utf-8":
            return result.json()
        elif content_type == "application/vnd.github.patch; charset=utf-8":
            return result.text
        elif content_type == "application/vnd.github.diff; charset=utf-8":
            return result.text

    def _post(self, path: str, *args, **kwargs):
        result = self._api.post(path, *args, **kwargs)
        return result

    @property
    def session(self) -> requests.Session:
        """Return the underlying HTTP session."""
        return self._api.session

    def build_pull_request(self, pull_number: int) -> "PullRequest":
        """Build a PullRequest object.

        This does the necessary network requests to collect the data."""
        data = self.get_pull_request(pull_number)
        return PullRequest(self, data)

    def list_pull_requests(self) -> list:
        """List all pull requests in the repo."""
        return self._repo_get("pulls")

    def get_pull_request(self, pull_number: int) -> dict:
        """Get a specific pull request from the repo."""
        return self._repo_get(f"pulls/{pull_number}")

    def get_diff(self, pull_number: int) -> str:
        """Fetch a diff, given a pull request number."""
        return self._get(
            f"{self.repo_base_url}/pulls/{pull_number}",
            headers={"Accept": "application/vnd.github.diff"},
        )

    def get_patch(self, pull_number: int) -> str:
        """Fetch a patch, given a pull request number."""
        return self._get(
            f"{self.repo_base_url}/pulls/{pull_number}",
            headers={"Accept": "application/vnd.github.patch"},
        )

    def open_pull_request(self, pull_number: int) -> dict:
        """Open the given pull request."""
        return self._post(
            f"{self.repo_base_url}/pulls/{pull_number}", json={"state": "open"}
        )

    def close_pull_request(self, pull_number: int) -> dict:
        """Close the given pull request."""
        return self._post(
            f"{self.repo_base_url}/pulls/{pull_number}", json={"state": "closed"}
        )

    def add_comment_to_pull_request(self, pull_number: int, comment: str) -> dict:
        """Add a comment to the given pull request."""
        return self._post(
            f"{self.repo_base_url}/issues/{pull_number}/comments",
            json={"body": comment},
        )


class PullRequest:
    """A class that parses data returned from the GitHub API for pull requests."""

    _client: GitHubAPIClient

    def __repr__(self) -> str:
        return f"Pull request #{self.number} ({self.head_repo_git_url})"

    def __init__(self, client: GitHubAPIClient, data: dict):
        self._client = client

        self.url = data["url"]
        self.base_ref = data["base"]["ref"]  # "target" branch name
        self.base_sha = data["base"]["sha"]  # "target" branch sha
        self.head_ref = data["head"]["ref"]  # "working" branch name
        self.head_sha = data["head"]["sha"]  # "working" branch sha

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

    @property
    def diff(self) -> str:
        return self._client.get_diff(self.diff_url)

    @property
    def patch(self) -> str:
        return self._client.get_patch(self.patch_url)

    def serialize(self) -> dict[str, str]:
        """Return a dictionary with various pull request data."""
        return {
            "url": self.url,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "base_user_login": self.base_user_login,
            "base_user_id": self.base_user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "merged_at": self.merged_at,
            "diff_url": self.diff_url,
            "patch_url": self.patch_url,
            "body": self.body,
            "is_draft": self.is_draft,
            "comments_url": self.comments_url,
            "commits_url": self.commits_url,
            "head_ref": self.head_ref,
            "head_sha": self.head_sha,
            "head_repo_git_url": self.head_repo_git_url,
            "html_url": self.html_url,
            "id": self.id,
            "number": self.number,
            "requested_reviewers": self.requested_reviewers,
            "requested_teams": self.requested_teams,
            "state": self.state,
            "title": self.title,
            "user_id": self.user_id,
            "user_html_url": self.user_html_url,
            "user_login": self.user_login,
        }

    def get_diff(self, client: GitHubAPIClient) -> str:
        """Return a single diff of the latest state for the PR.

        WARNING: The returned diff doesn't include any binary data.

        If Binary data is desired, the `get_patch` method should be used instead.
        """
        response = client.session.get(self.diff_url)
        response.raise_for_status()

        return response.text

    def get_patch(self, client: GitHubAPIClient) -> str:
        """Return a series of patches from the PR's commits.

        Patches from each commit are concatenated into a single string.

        This includes binary content, unlike `get_diff`.
        """
        response = client.session.get(self.patch_url)
        response.raise_for_status()

        return response.text


class PullRequestPatchHelper(PatchHelper):
    """A PatchHelper-like wrapper for GitHub pull requests.

    Due to the nature of pull requests, it only implement the data-getting
    functionality, and  doesn't implement the input and output
    methods.
    """

    _diff: str

    def __init__(self, client: GitHubAPIClient, pr: PullRequest):
        super().__init__()

        self._diff = pr.get_diff(client)

        user = f"{pr.user_login}@github-pr"
        # Consider the committer of the first patch to be the author.
        patch = pr.get_patch(client)
        for line in patch.splitlines():
            if match := self.USERNAME_RE.match(line):
                user = match["user"]
                break

        self.headers = {
            "date": self._get_timestamp_from_github_timestamp(pr.updated_at),
            "from": user,
            "subject": pr.body.splitlines()[0] if pr.body else "",
        }

    @classmethod
    def _get_timestamp_from_github_timestamp(cls, timestamp: str) -> str:
        timestamp_datetime = datetime.fromisoformat(timestamp)
        return str(math.floor(timestamp_datetime.timestamp()))

    @classmethod
    def from_string_io(cls, string_io: io.StringIO) -> "PatchHelper":
        """Implement the PatchHelper interface; not relevant for GitHub PRs."""
        raise NotImplementedError("`from_string_io` not implemented.")

    @classmethod
    def from_bytes_io(cls, bytes_io: io.BytesIO) -> "PatchHelper":
        """Implement the PatchHelper interface; not relevant for GitHub PRs."""
        raise NotImplementedError("`from_bytes_io` not implemented.")

    def get_commit_description(self) -> str:
        """Returns the commit description."""
        return self.get_header("subject")

    @override
    def get_diff(self) -> str:
        """Return the patch diff.

        WARNING: As of 2025-10-13, this doesn't include any binary data.
        """
        return self._diff

    @override
    def write(self, f: io.StringIO):
        """Implement the PatchHelper interface; not relevant for GitHub PRs."""
        raise NotImplementedError("`from_bytes_io` not implemented.")

    @override
    def parse_author_information(self) -> tuple[str, str]:
        """Return the author name and email from the patch."""
        line = f"From: {self.get_header('from')}"
        match = self.USERNAME_RE.match(line)
        return (match["name"], match["email"])

    @override
    def get_timestamp(self) -> str:
        """Return an `hg export` formatted timestamp."""
        return self.get_header("date")
