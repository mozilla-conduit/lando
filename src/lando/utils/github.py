import asyncio
import io
import logging
import math
from datetime import datetime
from enum import Enum

import requests
from django.conf import settings
from simple_github import AppAuth, AppInstallationAuth
from typing_extensions import override

# from lando.main.models.repo import Repo
from lando.main.scm.helpers import PatchHelper
from lando.utils.cache import cache_method

logger = logging.getLogger(__name__)


class GitHubAPI:
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
        url = f"{self.GITHUB_BASE_URL}/{path}"
        return self.session.get(url, *args, **kwargs)

    def post(self, path: str, *args, **kwargs) -> requests.Response:
        url = f"self.GITHUB_BASE_URL/{path}"
        return self.session.post(url, *args, **kwargs)


class GitHubAPIClient:
    client: GitHubAPI

    # repo: "Repo"
    repo_base_url: str

    def __init__(self, repo: "Repo"):
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

    @classmethod
    def convert_timestamp_from_github(cls, timestamp: str) -> str:
        timestamp_datetime = datetime.fromisoformat(timestamp)
        return str(math.floor(timestamp_datetime.timestamp()))

    @property
    def session(self) -> requests.Session:
        """Return the underlying HTTP session."""
        return self.client.session

    def list_pull_requests(self) -> list:
        return self.get("pulls")

    def get_pull_request(self, pull_number: int) -> dict:
        return self.get(f"pulls/{pull_number}")

    def get_diff(self, url: str) -> str:
        pass


def pr_cache_key(self: "PullRequest", *args, **kwargs) -> str:
    """Provide a cache key for PR methods that fetch data from GitHub.

    This method-like function cannot be part of the PullRequest, as it is used by method
    decorators when declaring the class.
    """
    return f"{self.id}{self.updated_at}"


class PullRequest:
    class StaleMetadataException(Exception):
        pass

    class UpstreamError(Exception):
        pass

    class Mergeability(str, Enum):
        CLEAN = "clean"
        DIRTY = "dirty"  # conflicts
        UNSTABLE = "unstable"  # checks failing
        BLOCKED = "blocked"  # blocking rule not satisfied
        UNKNOWN = "unknown"
        DRAFT = "draft"

    class State(str, Enum):
        OPEN = "open"
        CLOSED = "closed"

    class Review(str, Enum):
        APPROVED = "APPROVED"
        CHANGES_REQUESTED = "CHANGES_REQUESTED"
        DISMISSED = "DISMISSED"

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
        self.mergeable_state = data["mergeable_state"]
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

    def serialize(self) -> dict[str, str]:
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
            "mergeable_state": self.mergeable_state,
            "number": self.number,
            "requested_reviewers": self.requested_reviewers,
            "requested_teams": self.requested_teams,
            "state": self.state,
            "title": self.title,
            "user_id": self.user_id,
            "user_html_url": self.user_html_url,
            "user_login": self.user_login,
        }

    @cache_method(pr_cache_key)
    def get_comments(self, client: GitHubAPIClient) -> list:
        """Return a list of comments on the whole PR."""
        # `issues` is correct here, using `pull` instead would return comments on diffs.
        comments = client.get(f"issues/{self.number}/comments")

        if any(
            client.convert_timestamp_from_github(comment["updated_at"])
            > client.convert_timestamp_from_github(self.updated_at)
            for comment in comments
        ):
            raise self.StaleMetadataException(
                "Comments were changed while collecting PR information."
            )

        return comments

    @cache_method(pr_cache_key)
    def get_commits(self, client: GitHubAPIClient) -> dict:
        """Return a list of commits for the PR."""
        commits = client.get(f"pulls/{self.number}/commits")

        if commits[-1]["sha"] != self.head_sha:
            raise self.StaleMetadataException(
                "Head commit changed while collecting PR information."
            )

        # XXX: What happens if a commit has been committed in the past, but has only
        # been pushed now?
        if any(
            client.convert_timestamp_from_github(commit["commit"]["committer"]["date"])
            > client.convert_timestamp_from_github(self.updated_at)
            for commit in commits
        ):
            raise self.StaleMetadataException(
                "Commits were added while collecting PR information."
            )

        return commits

    @cache_method(pr_cache_key)
    def get_commit_comments(self, client: GitHubAPIClient) -> list:
        """Return a list of comments on specific changes of the PR."""
        # NOTE: We use the GraphQL API for this on, as the comment-resolution
        # information is not available via the REST API [0].
        #
        # NOTE: While there are many comment fields accessible. It seems the only one
        # that reliably return data is pullRequest.reviews[].comments[] [1]. Most
        # notably, pullRequest.commits[].comments[] seems to always be empty. But that's not what
        # we need anyway. What we're after is reviewThreads, which are resolvable.
        #
        # [0] https://github.com/orgs/community/discussions/9175#discussioncomment-9008230
        # [1] https://github.com/orgs/community/discussions/24666#discussioncomment-3244969
        #
        comments_query = """
          query($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
              pullRequest(number: $number) {
                reviewThreads(first: 100) {
                  nodes {
                    comments(first: 1) {
                      nodes {
                        id
                        body
                        url
                        updatedAt
                      }
                    }
                    isResolved
                  }
                }
                updatedAt
              }
            }
          }
          """
        comments_response = client.session.post(
            "https://api.github.com/graphql",
            json={
                "query": comments_query,
                "variables": {
                    "owner": client.repo._github_repo_org,
                    "repo": client.repo.git_repo_name,
                    "number": self.number,
                },
            },
        )
        comments_response.raise_for_status()
        comments_response_json = comments_response.json()
        if "errors" in comments_response_json:
            raise self.UpstreamError(
                f"Error from GitHub GraphQL: {comments_response_json}"
            )

        comments_dict = comments_response_json["data"]["repository"]["pullRequest"][
            "reviewThreads"
        ]["nodes"]

        comments = []

        for thread in comments_dict:
            # We only grab the first comment of each thread.
            comment = thread["comments"]["nodes"][0]
            comment["updated_at"] = comment["updatedAt"]
            del comment["updatedAt"]
            comment["is_resolved"] = thread["isResolved"]

            comments.append(comment)

        if any(
            client.convert_timestamp_from_github(comment["updated_at"])
            > client.convert_timestamp_from_github(self.updated_at)
            for comment in comments
        ):
            raise self.StaleMetadataException(
                "Comments were changed while collecting PR information."
            )

        return comments

    def get_diff(self, client: GitHubAPIClient) -> str:
        """Return a single diff of the latest state for the PR.

        WARNING: The returned diff doesn't include any binary data.

        If Binary data is desired, the `get_patch` method should be used instead.
        """
        response = client.session.get(self.diff_url)
        response.raise_for_status()

        return response.text

    @cache_method(pr_cache_key)
    def get_labels(self, client: GitHubAPIClient) -> list:
        """Return a list of labels for the PR."""
        # `issues` is correct here
        labels = client.get(f"issues/{self.number}/labels")

        return labels

    def get_patch(self, client: GitHubAPIClient) -> str:
        """Return a series of patches from the PR's commits.

        Patches from each commit are concatenated into a single string.

        This includes binary content, unlike `get_diff`.
        """
        response = client.session.get(self.patch_url)
        response.raise_for_status()

        return response.text

    @cache_method(pr_cache_key)
    def get_reviews(self, client: GitHubAPIClient) -> list:
        """Return a list of reviews for the PR."""
        reviews = client.get(f"pulls/{self.number}/reviews")

        if any(
            client.convert_timestamp_from_github(review["submitted_at"])
            > client.convert_timestamp_from_github(self.updated_at)
            for review in reviews
        ):
            raise self.StaleMetadataException(
                "Reviews were added while collecting PR information."
            )

        return reviews


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
            "date": client.convert_timestamp_from_github(pr.updated_at),
            "from": user,
            "subject": pr.body.splitlines()[0] if pr.body else "",
        }

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
