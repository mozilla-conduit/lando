import asyncio
import io
import logging
import math
import re
from collections import Counter
from datetime import datetime
from enum import Enum

import requests
from django.conf import settings
from simple_github import AppAuth, AppInstallationAuth
from typing_extensions import override

from lando.api.legacy.commit_message import replace_reviewers
from lando.main.scm.helpers import PatchHelper
from lando.utils.cache import cache_method
from lando.utils.const import URL_USERINFO_RE

logger = logging.getLogger(__name__)


class GitHub:
    """Work with authentication to GitHub repositories."""

    GITHUB_URL_RE = re.compile(
        rf"https://{URL_USERINFO_RE.pattern}?github.com/(?P<owner>[-A-Za-z0-9]+)/(?P<repo>[^/]+?)(?:\.git)?(?:/|$)"
    )

    repo_url: str
    repo_owner: str
    repo_name: str
    userinfo: str

    def __init__(self, repo_url: str):
        self.repo_url = repo_url

        parsed_url_data = self.parse_url(self.repo_url)

        if parsed_url_data is None:
            raise ValueError(f"Cannot parse URL as GitHub repo: {repo_url}")

        self.repo_owner = parsed_url_data["owner"]
        self.repo_name = parsed_url_data["repo"]
        self.userinfo = parsed_url_data["userinfo"]

    @classmethod
    def is_supported_url(cls, url: str) -> bool:
        """Determine whether the passed URL is a supported GitHub URL."""
        return cls.parse_url(url) is not None

    @classmethod
    def parse_url(cls, url: str) -> re.Match[str] | None:
        """Parse GitHub data from URL, or return None if not Github.

        Note: no normalisation is performed on the URL
        """
        return re.match(cls.GITHUB_URL_RE, url)

    @property
    def authenticated_url(self) -> str:
        """Return an authenticated URL, suitable for use with `git` to push and pull.

        If the URL already has authentication parameters, it is returned verbatim. If
        not, a token is fetched by the GitHub app, and inserted into the USERINFO part of
        the URL, without any other changes (e.g., in the REST path or Query String).
        """
        if self.userinfo:
            # We only fetch a token if no authentication is explicitly specified in
            # the repo_url.
            return self.repo_url

        logger.info(
            f"Obtaining fresh GitHub token for GitHub repo at {self.repo_url}",
        )

        token = self._fetch_token()

        if token:
            return self.repo_url.replace(
                "https://github.com", f"https://git:{token}@github.com"
            )

        # We didn't get a token
        logger.warning(f"Couldn't obtain a token for GitHub repo at {self.repo_url}")
        return self.repo_url

    def _fetch_token(self) -> str | None:
        """Obtain a fresh GitHub token to push to the specified repo.

        This relies on GITHUB_APP_ID and GITHUB_APP_PRIVKEY to be set in the
        environment. Returns None if those are missing.

        The app with ID GITHUB_APP_ID needs to be enabled for the target repo.

        """
        app_id = settings.GITHUB_APP_ID
        private_key = settings.GITHUB_APP_PRIVKEY

        if not app_id or not private_key:
            logger.warning(
                f"Missing GITHUB_APP_ID or GITHUB_APP_PRIVKEY to authenticate against GitHub repo at {self.repo_url}",
            )
            return None

        app_auth = AppAuth(
            app_id,
            private_key,
        )
        session = AppInstallationAuth(
            app_auth, self.repo_owner, repositories=[self.repo_name]
        )
        return asyncio.run(session.get_token())


class GitHubAPI(GitHub):
    """A simple wrapper that authenticates with and communicates with the GitHub API."""

    session: requests.Session

    GITHUB_BASE_URL = "https://api.github.com"

    def __init__(self, repo_url: str):
        super().__init__(repo_url)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._fetch_token()}",
                "User-Agent": settings.HTTP_USER_AGENT,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

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

    class UpstreamError(Exception):
        pass

    def __init__(self, repo_url: str):
        self._api = GitHubAPI(repo_url)
        self.repo_base_url = f"repos/{self.repo_owner}/{self.repo_name}"

    @property
    def session(self) -> requests.Session:
        """An authenticated requests Session."""
        return self._api.session

    @property
    def repo_owner(self) -> str:
        return self._api.repo_owner

    @property
    def repo_name(self) -> str:
        return self._api.repo_name

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
        return result.json()

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

    def get_pull_request_comments(self, pull_number: int) -> list:
        """Return a list of comments on the whole PR."""
        # `issues` is correct here, using `pull` instead would return comments on diffs.
        return self._repo_get(f"issues/{pull_number}/comments")

    def get_pull_request_commits(self, pull_number: int) -> list[dict]:
        """Get all commits from specific pull request from the repo."""
        return self._repo_get(f"pulls/{pull_number}/commits")

    def get_pull_request_commits_comments(self, pull_number: int) -> list:
        """Return a list of comments on specific changes of the PR."""
        # NOTE: We use the GraphQL API for this one, as the comment-resolution
        # information is not available via the REST API [0].
        #
        # NOTE: While there are many comment fields accessible. It seems the only one
        # that reliably return data is pullRequest.reviews[].comments[] [1]. Most
        # notably, pullRequest.commits[].comments[] seems to always be empty.
        #
        # But that's not what we need anyway. What we're after is reviewThreads,
        # which are resolvable.
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
        comments_response = self.session.post(
            "https://api.github.com/graphql",
            json={
                "query": comments_query,
                "variables": {
                    "owner": self.repo_owner,
                    "repo": self.repo_name,
                    "number": pull_number,
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

        return comments

    def get_pull_request_labels(self, pull_number: int) -> list:
        """Return a list of labels for the PR."""
        # `issues` is correct here
        labels = self._repo_get(f"issues/{pull_number}/labels")

        return labels

    def get_pull_request_reviews(self, pull_number: int) -> list:
        """Return a list of reviews for the PR."""
        return self._repo_get(f"pulls/{pull_number}/reviews")

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

    @classmethod
    def convert_timestamp_from_github(cls, timestamp: str) -> str:
        timestamp_datetime = datetime.fromisoformat(timestamp)
        return str(math.floor(timestamp_datetime.timestamp()))


def pr_cache_key(self: "PullRequest", *args, **kwargs) -> str:
    """Provide a cache key for PR methods that fetch data from GitHub.

    This method-like function cannot be part of the PullRequest, as it is used by method
    decorators when declaring the class.
    """
    return f"{self.id}{self.updated_at}"


# Specialised decorator which embeds the PR-specific cache-key builder.
pr_cache_method = cache_method(pr_cache_key)


class PullRequest:
    """A class that parses data returned from the GitHub API for pull requests."""

    class StaleMetadataException(Exception):
        pass

    class Mergeability(str, Enum):
        """Mergeability of a PR.

        This is not documented for the REST API, but the GraphQL doc has some details
        [0].

        [0] https://docs.github.com/en/graphql/reference/enums#mergestatestatus
        """

        BEHIND = "behind"  # The head ref is out of date.
        BLOCKED = "blocked"  # The merge is blocked.
        CLEAN = "clean"  # Mergeable and passing commit status.
        DIRTY = "dirty"  # The merge commit cannot be cleanly created.
        DRAFT = "draft"  # The merge is blocked due to the pull request being a draft.
        HAS_HOOKS = (
            "has_hooks"  # Mergeable with passing commit status and pre-receive hooks.
        )
        UNKNOWN = "unknown"  # The state cannot currently be determined.
        UNSTABLE = "unstable"  # Mergeable with non-passing commit status.

    class State(str, Enum):
        """State of a PR."""

        OPEN = "open"
        CLOSED = "closed"

    class Review(str, Enum):
        """Type of a review on a PR."""

        APPROVED = "APPROVED"
        CHANGES_REQUESTED = "CHANGES_REQUESTED"
        DISMISSED = "DISMISSED"

    client: GitHubAPIClient

    def __repr__(self) -> str:
        return f"Pull request #{self.number} ({self.head_repo_git_url})"

    def __init__(self, client: GitHubAPIClient, data: dict):
        self.client = client

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
        self.labels = data["labels"]
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

    def _select_commit_author(
        self, commits: list[dict]
    ) -> tuple[str | None, str | None]:
        """Select the most common author in commits."""
        # This method is ported from lando.api.legacy.revisions.select_diff_author.
        commits = [commit["commit"] for commit in commits]
        if not commits:
            return None, None

        # Below is copied verbatim from the legacy method.
        authors = [c.get("author", {}) for c in commits]
        authors = Counter((a.get("name"), a.get("email")) for a in authors)
        authors = authors.most_common(1)
        return authors[0][0] if authors else (None, None)

    @property
    @pr_cache_method
    def author(self) -> tuple[str | None, str | None]:
        return self._select_commit_author(self.commits)

    @property
    def diff(self) -> str:
        return self.client.get_diff(self.number)

    @property
    @pr_cache_method
    def comments(self) -> list:
        comments = self.client.get_pull_request_comments(self.number)
        if any(
            self.client.convert_timestamp_from_github(comment["updated_at"])
            > self.client.convert_timestamp_from_github(self.updated_at)
            for comment in comments
        ):
            raise self.StaleMetadataException(
                "Comments were changed while collecting PR information."
            )

        return comments

    @property
    @pr_cache_method
    def commits(self) -> list[dict]:
        commits = self.client.get_pull_request_commits(self.number)

        if commits[-1]["sha"] != self.head_sha:
            raise self.StaleMetadataException(
                "Head commit changed while collecting PR information."
            )

        # XXX: What happens if a commit has been committed in the past, but has only
        # been pushed now?
        if any(
            self.client.convert_timestamp_from_github(
                commit["commit"]["committer"]["date"]
            )
            > self.client.convert_timestamp_from_github(self.updated_at)
            for commit in commits
        ):
            raise self.StaleMetadataException(
                "Commits were added while collecting PR information."
            )

        return commits

    @property
    @pr_cache_method
    def commit_comments(self) -> list:
        """Return a list of comments on specific changes of the PR."""
        commits_comments = self.client.get_pull_request_commits_comments(self.number)

        if any(
            self.client.convert_timestamp_from_github(comment["updated_at"])
            > self.client.convert_timestamp_from_github(self.updated_at)
            for comment in commits_comments
        ):
            raise self.StaleMetadataException(
                "Comments were changed while collecting PR information."
            )

        return commits_comments

    @property
    def patch(self) -> str:
        return self.client.get_patch(self.number)

    @property
    def reviews_summary(self) -> dict[str, str]:
        """Get a simple dict of reviewers and the state of their review."""
        return {review["user"]["login"]: review["state"] for review in self.reviews}

    @property
    @pr_cache_method
    def reviews(self) -> list:
        """Return a list of reviews for the PR."""
        reviews = self.client.get_pull_request_reviews(self.number)

        if any(
            self.client.convert_timestamp_from_github(review["submitted_at"])
            > self.client.convert_timestamp_from_github(self.updated_at)
            for review in reviews
        ):
            raise self.StaleMetadataException(
                "Reviews were added while collecting PR information."
            )

        return reviews

    @property
    def commit_message(self) -> str:
        """Return a string combining the pull request title with reviewers, description, and URL."""

        reviewers = [
            u
            for u in self.reviews_summary
            if self.reviews_summary.get(u) == self.Review.APPROVED
        ]
        approvals = []

        lines = [replace_reviewers(self.title, reviewers, approvals), ""]

        if self.body:
            lines += [self.body, ""]

        lines.append(f"closes: {self.html_url}")

        return "\n".join(lines)

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


class PullRequestPatchHelper(PatchHelper):
    """A PatchHelper-like wrapper for GitHub pull requests.

    Due to the nature of pull requests, it only implement the data-getting
    functionality, and doesn't implement the input and output methods.
    """

    _diff: str

    _author_name: str
    _author_email: str
    _pr: PullRequest

    def __init__(self, pr: PullRequest):
        super().__init__()

        self._pr = pr

        self._diff = pr.diff

        author_name, author_email = self._pr.author

        self.headers = {
            "date": self._get_timestamp_from_github_timestamp(pr.updated_at),
            "from": f"{author_name} <{author_email}>",
            "subject": pr.title,
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
        return self._pr.author

    @override
    def get_timestamp(self) -> str:
        """Return an `hg export` formatted timestamp."""
        return self.get_header("date")
