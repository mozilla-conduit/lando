import logging
from abc import ABC, abstractmethod

from django.http import HttpRequest
from typing_extensions import override

from lando.main.models.repo import Repo
from lando.utils.github import GitHubAPIClient, PullRequest

logger = logging.getLogger("__name__")


class PullRequestCheck(ABC):
    @classmethod
    @abstractmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        """Inspect the PR for on issue, and return a message string if present."""


#
# BLOCKERS
#


class PullRequestBlocker(PullRequestCheck, ABC):
    """Parent class for blocker checks."""


class PullRequestUserSCMLevelBlocker(PullRequestBlocker):
    """You have insufficient permissions to land or your access has expired."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # We specifically check the direct user permissions, rather than the union of
        # those that could have been inherited from group or other roles (e.g., admin).
        if target_repo.required_permission in request.user.get_user_permissions():
            return []

        return [cls.__doc__]


# XXX: Irrelevant.
# class PullRequestUnsupportedRepoBlocker(PullRequestBlocker):
#     """Repository is not supported by Lando."""
#
#     @override
#     @classmethod
#     def run(cls, client: GitHubAPIClient, pull_request: PullRequest, target_repo: Repo, request: HttpRequest, request: HttpRequest) -> list[str]:
#         raise NotImplementedError


# XXX: Not currently needed.
# class PullRequestOpenParentsBlocker(PullRequestBlocker):
#     """Depends on multiple open parents."""
#
#     @override
#     @classmethod
#     def run(cls, client: GitHubAPIClient, pull_request: PullRequest, target_repo: Repo, request: HttpRequest, request: HttpRequest) -> list[str]:
#         raise NotImplementedError


class PullRequestClosedBlocker(PullRequestBlocker):
    """Revision is closed."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.state == pull_request.State.CLOSED:
            return [cls.__doc__]

        return []


# XXX: Not relevant to PRs.
# class PullRequestLatestDiffsBlocker(PullRequestBlocker):
#     """A requested diff is not the latest."""
#
#     @override
#     @classmethod
#     def run(cls, client: GitHubAPIClient, pull_request: PullRequest, target_repo: Repo, request: HttpRequest, request: HttpRequest) -> list[str]:
#         raise NotImplementedError


class PullRequestDiffAuthorIsKnownBlocker(PullRequestBlocker):
    # """"Diff does not have proper author information in Phabricator."""
    """Commit does not have proper author information."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        commits = pull_request.get_commits(client)

        messages = []

        for commit in commits:
            if (
                not commit["commit"]["author"]["name"]
                or not commit["commit"]["author"]["email"]
            ):
                messages.append(
                    f"{cls.__doc__} {commit['sha']}: {commit['commit']['message']} ({commit['commit']['url']})"
                )

        return messages


class PullRequestAuthorPlannedChangesBlocker(PullRequestBlocker):
    """The author has indicated they are planning changes to this revision."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.is_draft:
            return [cls.__doc__]

        return []


class PullRequestUpliftApprovalBlocker(PullRequestBlocker):
    """The release-managers group did not accept the stack."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        raise Exception("This check should be at the lando level")


class PullRequestRevisionDataClassificationBlocker(PullRequestBlocker):
    """Revision makes changes to data collection and should have its data classification assessed before landing."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if "needs-data-classification" in [
            label["name"] for label in pull_request.get_labels(client)
        ]:
            return [cls.__doc__]

        return []


# XXX: Not currently needed.
# class PullRequestOpenAncestorBlocker(PullRequestBlocker):
#     """Has an open ancestor revision that is blocked."""
#
#     @override
#     @classmethod
#     def run(cls, client: GitHubAPIClient, pull_request: PullRequest, target_repo: Repo, request: HttpRequest, request: HttpRequest) -> list[str]:
#         raise NotImplementedError


class PullRequestChecks:
    """Utility class to check a GitHub pull request for a given list of issues."""

    _client: GitHubAPIClient
    _request: HttpRequest
    _target_repo: Repo

    def __init__(
        self,
        client: GitHubAPIClient,
        target_repo: Repo,
        request: HttpRequest,
    ):
        self._client = client
        self._target_repo = target_repo
        self._request = request

    def run(
        self, checks_list: list[type[PullRequestCheck]], pull_request: PullRequest
    ) -> list[str]:
        messages = []

        for check in checks_list:
            try:
                if outcome := check.run(
                    self._client, pull_request, self._target_repo, self._request
                ):
                    messages.extend(outcome)
            except NotImplementedError:
                messages.append(f"{check.__name__} is not implemented")

            except Exception as exc:
                logger.exception(exc)
                messages.append(f"{check.__name__} failed to run with error: {exc}")

        return messages


ALL_PULLREQUEST_BLOCKERS = PullRequestBlocker.__subclasses__()
