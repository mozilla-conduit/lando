from abc import ABC, abstractmethod

from typing_extensions import override

from lando.utils.github import GitHubAPIClient, PullRequest


class PullRequestCheck(ABC):
    @classmethod
    @abstractmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        """Inspect the PR for on issue, and return a message string if present."""


#
# BLOCKERS
#


class PullRequestBlocker(PullRequestCheck, ABC):
    """Parent class for blocker checks."""


#
# WARNINGS
#


class PullRequestWarning(PullRequestCheck, ABC):
    """Parent class for warning checks."""


class PullRequestBlockingReviewsWarning(PullRequestWarning):
    """Has a review intended to block landing."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        raise NotImplementedError


class PullRequestPreviouslyLandedWarning(PullRequestWarning):
    """Has previously landed."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        if not pull_request.merged_at:
            return None

        return cls.__doc__


class PullRequestNotAcceptedWarning(PullRequestWarning):
    """Is not Accepted."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        reviews = pull_request.get_reviews(client)

        if any(review["state"] == "APPROVED" for review in reviews):
            return None

        return cls.__doc__


class PullRequestReviewsNotCurrentWarning(PullRequestWarning):
    """No reviewer has accepted the current diff."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        reviews = pull_request.get_reviews(client)

        if pull_request.head_sha in [
            review["commit_id"] for review in reviews if review["state"] == "APPROVED"
        ]:
            return None

        return cls.__doc__


class PullRequestSecureRevisionWarning(PullRequestWarning):
    """Is a secure pull request and should follow the Security Bug Approval Process."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        raise NotImplementedError


class PullRequestMissingTestingTagWarning(PullRequestWarning):
    """Pull request is missing a Testing Policy Project Tag."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        raise NotImplementedError


class PullRequestDiffWarning(PullRequestWarning):
    """Pull request has a diff warning."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        raise NotImplementedError


class PullRequestWIPWarning(PullRequestWarning):
    """Pull request is marked as WIP."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        if pull_request.title.lower().startswith("wip:"):
            return cls.__doc__

        return None


class PullRequestCodeFreezeWarning(PullRequestWarning):
    """Repository is under a soft code freeze."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        raise NotImplementedError


class PullRequestUnresolvedCommentsWarning(PullRequestWarning):
    """Pull request has unresolved comments."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        raise NotImplementedError


class PullRequestMultipleAuthorsWarning(PullRequestWarning):
    """Pull request has multiple authors."""

    @override
    @classmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        if (
            len({commit["author"]["id"] for commit in pull_request.get_commits(client)})
            == 1
        ):
            return ""

        return cls.__doc__


class PullRequestChecks:
    """Utility class to check a GitHub pull request for a given list of issues."""

    _client: GitHubAPIClient

    def __init__(self, client: GitHubAPIClient):
        self._client = client

    def run(
        self, checks_list: list[type[PullRequestCheck]], pull_request: PullRequest
    ) -> list[str]:
        messages = []

        for check in checks_list:
            try:
                if outcome := check.run(self._client, pull_request):
                    messages.append(outcome)
            except NotImplementedError:
                messages.append(f"{check.__name__} is not implemented")

            except Exception as exc:
                messages.append(f"{check.__name__} failed to run with error: {exc}")

        return messages


ALL_PULLREQUEST_BLOCKERS = PullRequestBlocker.__subclasses__()
ALL_PULLREQUEST_WARNINGS = PullRequestWarning.__subclasses__()
