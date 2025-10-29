import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import requests
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

# GITHUB-SPECIFIC CHECKS


class PullRequestBaseBranchDoesNotMatchTree(PullRequestBlocker):
    """The base branch for this PR doesn't match this Tree."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.base_ref != target_repo.default_branch:
            return [cls.__doc__]

        return []


class PullRequestConflictWithBaseBranch(PullRequestBlocker):
    """This Pull Request has conflicts that must be resolved."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.mergeable_state == pull_request.Mergeability.DIRTY:
            return [cls.__doc__]

        return []


class PullRequestFailingCheck(PullRequestBlocker):
    """This Pull Request has has some failing checks."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # If we need more details on which tests are failing, we could use the commit
        # statuses endpoint instead [0].
        #
        # [0] https://docs.github.com/en/rest/commits/statuses?apiVersion=2022-11-28
        if pull_request.mergeable_state == pull_request.Mergeability.UNSTABLE:
            return [cls.__doc__]

        return []


#
# WARNINGS
#


class PullRequestWarning(PullRequestCheck, ABC):
    """Parent class for warning checks."""


class PullRequestBlockingReviewsWarning(PullRequestWarning):
    """Has a review intended to block landing."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviews = pull_request.get_reviews(client)

        messages = []

        for review in reviews:
            if review["state"] == pull_request.Review.CHANGES_REQUESTED:
                messages.append(
                    f"{cls.__doc__} {review['body'].splitlines()[0]}… {review['html_url']})"
                )

        return messages


class PullRequestPreviouslyLandedWarning(PullRequestWarning):
    """Has previously landed."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if not pull_request.merged_at:
            return []

        return [cls.__doc__]


class PullRequestNotAcceptedWarning(PullRequestWarning):
    """Is not Accepted."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviews = pull_request.get_reviews(client)

        if any(review["state"] == pull_request.Review.APPROVED for review in reviews):
            return []

        return [cls.__doc__]


class PullRequestReviewsNotCurrentWarning(PullRequestWarning):
    """No reviewer has accepted the current diff."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviews = pull_request.get_reviews(client)

        if pull_request.head_sha in [
            review["commit_id"]
            for review in reviews
            if review["state"] == pull_request.Review.APPROVED
        ]:
            return []

        return [cls.__doc__]


class PullRequestSecureRevisionWarning(PullRequestWarning):
    """Is a secure pull request and should follow the Security Bug Approval Process."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        raise NotImplementedError


class PullRequestMissingTestingTagWarning(PullRequestWarning):
    """Pull request is missing a Testing Policy Project Tag."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # Only allow a single testing tag.
        if (
            len(
                [
                    label["name"]
                    for label in pull_request.get_labels(client)
                    if label["name"].startswith("testing")
                ]
            )
            != 1
        ):
            return [cls.__doc__]

        return []


class PullRequestDiffWarning(PullRequestWarning):
    """Pull request has a diff warning."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        raise NotImplementedError


class PullRequestWIPWarning(PullRequestWarning):
    """Pull request is marked as WIP."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.title.lower().startswith("wip:"):
            return [cls.__doc__]

        return []


class PullRequestCodeFreezeWarning(PullRequestWarning):
    """Repository is under a soft code freeze."""

    # The code freeze dates generally correspond to PST work days.
    CODE_FREEZE_OFFSET = "-0800"

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if not target_repo.product_details_url:
            return []

        try:
            product_details = requests.get(target_repo.product_details_url).json()
        except requests.exceptions.RequestException as e:
            logger.exception(e)
            return ["Could not retrieve repository's code freeze status."]

        freeze_date_str = product_details.get("NEXT_SOFTFREEZE_DATE")
        merge_date_str = product_details.get("NEXT_MERGE_DATE")
        # If the JSON doesn't have these keys, this warning isn't applicable
        if not freeze_date_str or not merge_date_str:
            return []

        today = datetime.now(tz=timezone.utc)
        freeze_date = datetime.strptime(
            f"{freeze_date_str} {cls.CODE_FREEZE_OFFSET}",
            "%Y-%m-%d %z",
        ).replace(tzinfo=timezone.utc)
        if today < freeze_date:
            return []

        merge_date = datetime.strptime(
            f"{merge_date_str} {cls.CODE_FREEZE_OFFSET}",
            "%Y-%m-%d %z",
        ).replace(tzinfo=timezone.utc)

        if freeze_date <= today <= merge_date:
            return [f"Repository is under a soft code freeze (ends {merge_date_str})."]

        return []


class PullRequestUnresolvedCommentsWarning(PullRequestWarning):
    """Pull request has unresolved comments."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        commit_comments = pull_request.get_commit_comments(client)
        messages = []

        for comment in commit_comments:
            if not comment["is_resolved"]:
                messages.append(f"{cls.__doc__} {comment['body']} ({comment['url']})")

        return messages


class PullRequestMultipleAuthorsWarning(PullRequestWarning):
    """Pull request has multiple authors."""

    @override
    @classmethod
    def run(
        cls,
        client: GitHubAPIClient,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if (
            len(
                authors :=
                # Note: this is a set comprehension, so each element is unique.
                {
                    f"{commit['commit']['author']['name']} <{commit['commit']['author']['email']}>"
                    for commit in pull_request.get_commits(client)
                }
            )
            != 1
        ):
            return [cls.__doc__ + " " + (", ".join(authors))]

        return []


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
ALL_PULLREQUEST_WARNINGS = PullRequestWarning.__subclasses__()
