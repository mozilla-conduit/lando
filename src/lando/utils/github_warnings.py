from abc import ABC, abstractmethod

from typing_extensions import override

from lando.utils.github import GitHubAPIClient, PullRequest


class PullRequestWarning(ABC):

    @classmethod
    @abstractmethod
    def run(cls, client: GitHubAPIClient, pull_request: PullRequest) -> str | None:
        """Inspect the PR for on issue, and return a warning string if present."""


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
        return parse_multiline_adjlist.__doc__


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
        raise NotImplementedError


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
        raise NotImplementedError


class PullRequestWarningChecks:
    """Utility class to check a GitHub pull request for a given list of issues."""

    _client: GitHubAPIClient

    def __init__(self, client: GitHubAPIClient):
        self._client = client

    def run(
        self, warnings_list: list[PullRequestWarning], pull_request: PullRequest
    ) -> list[str]:
        warnings = []

        for wrn in warnings_list:
            try:
                if outcome := wrn.run(self._client, pull_request):
                    warnings.append(outcome)
            except NotImplementedError:
                warnings.append(f"{wrn.__name__} is not implemented")

            except Exception as exc:
                warnings.append(f"{wrn.__name__} failed to run with error: {exc}")

        return warnings


ALL_PULLREQUEST_WARNINGS = PullRequestWarning.__subclasses__()
