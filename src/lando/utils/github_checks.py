import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterable

import requests
from django.http import HttpRequest
from typing_extensions import override

from lando.main.models.jobs import JobStatus
from lando.main.models.landing_job import get_jobs_for_pull
from lando.main.models.repo import Repo
from lando.utils.github import GitHubAPIClient, PullRequest
from lando.utils.landing_checks import Check

logger = logging.getLogger("__name__")


class PullRequestCheck(Check, ABC):
    @classmethod
    @abstractmethod
    def run(
        cls,
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
    def name(cls) -> str:
        return "PullRequestUserSCMLevelBlocker"

    @override
    @classmethod
    def description(cls) -> str:
        return "You have insufficient permissions to land or your access has expired."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # We specifically check the direct user permissions, rather than the union of
        # those that could have been inherited from group or other roles (e.g., admin).
        if target_repo.required_permission in request.user.get_user_permissions():
            return []

        return [cls.description()]


class PullRequestClosedBlocker(PullRequestBlocker):
    """Revision is closed."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestClosedBlocker"

    @override
    @classmethod
    def description(cls) -> str:
        return "Revision is closed."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.state == pull_request.State.CLOSED:
            return [cls.description()]

        return []


class PullRequestDiffAuthorIsKnownBlocker(PullRequestBlocker):
    # """"Diff does not have proper author information in Phabricator."""
    """Commit does not have proper author information."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestDiffAuthorIsKnownBlocker"

    @override
    @classmethod
    def description(cls) -> str:
        return "Commit does not have proper author information."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        commits = pull_request.commits

        messages = []

        for commit in commits:
            if (
                not commit["commit"]["author"]["name"]
                or not commit["commit"]["author"]["email"]
            ):
                messages.append(
                    f"{cls.description()} {commit['sha']}: {commit['commit']['message']} ({commit['html_url']})"
                )

        return messages


class PullRequestAuthorPlannedChangesBlocker(PullRequestBlocker):
    """The author has indicated they are planning changes to this revision."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestAuthorPlannedChangesBlocker"

    @override
    @classmethod
    def description(cls) -> str:
        return "The author has indicated they are planning changes to this revision."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.is_draft:
            return [cls.description()]

        return []


class PullRequestRevisionDataClassificationBlocker(PullRequestBlocker):
    """Revision makes changes to data collection and should have its data classification assessed before landing."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestRevisionDataClassificationBlocker"

    @override
    @classmethod
    def description(cls) -> str:
        return "Revision makes changes to data collection and should have its data classification assessed before landing."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if "needs-data-classification" in [
            label["name"] for label in pull_request.labels
        ]:
            return [cls.description()]

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
    def name(cls) -> str:
        return "PullRequestBlockingReviewsWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Has a review intended to block landing."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviews = pull_request.reviews

        messages = []

        for review in reviews:
            if review["state"] == pull_request.Review.CHANGES_REQUESTED:
                messages.append(
                    f"{cls.description()} {review['body'].splitlines()[0]}… {review['html_url']})"
                )

        return messages


class PullRequestPreviouslyLandedWarning(PullRequestWarning):
    """Has previously landed."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestPreviouslyLandedWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Has previously landed."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        jobs = get_jobs_for_pull(target_repo, pull_request.number)

        if any(job.status == JobStatus.LANDED for job in jobs):
            return [cls.description()]

        return []


class PullRequestNotAcceptedWarning(PullRequestWarning):
    """Is not Accepted."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestNotAcceptedWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Is not Accepted."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviews = pull_request.reviews

        if any(review["state"] == pull_request.Review.APPROVED for review in reviews):
            return []

        return [cls.description()]


class PullRequestReviewsNotCurrentWarning(PullRequestWarning):
    """No reviewer has accepted the current diff."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestReviewsNotCurrentWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "No reviewer has accepted the current diff."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviews = pull_request.reviews

        if pull_request.head_sha in [
            review["commit_id"]
            for review in reviews
            if review["state"] == pull_request.Review.APPROVED
        ]:
            return []

        return [cls.description()]


class PullRequestMissingTestingTagWarning(PullRequestWarning):
    """Pull request is missing a Testing Policy Project Tag."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestMissingTestingTagWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Pull request is missing a Testing Policy Project Tag."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # Only allow a single testing tag.
        if (
            len(
                [
                    label["name"]
                    for label in pull_request.labels
                    if label["name"].startswith("testing")
                ]
            )
            != 1
        ):
            return [cls.description()]

        return []


class PullRequestDiffWarning(PullRequestWarning):
    """Pull request has a diff warning."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestDiffWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Pull request has a diff warning."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        raise NotImplementedError


class PullRequestWIPWarning(PullRequestWarning):
    """Pull request is marked as WIP."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestWIPWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Pull request is marked as WIP."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.title.lower().startswith("wip:"):
            return [cls.description()]

        return []


class PullRequestCodeFreezeWarning(PullRequestWarning):
    """Repository is under a soft code freeze."""

    # The code freeze dates generally correspond to PST work days.
    CODE_FREEZE_OFFSET = "-0800"

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestCodeFreezeWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Repository is under a soft code freeze."

    @override
    @classmethod
    def run(
        cls,
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
            return [
                f"Could not retrieve repository's code freeze status from {target_repo.product_details_url}."
            ]

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
    def name(cls) -> str:
        return "PullRequestUnresolvedCommentsWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Pull request has unresolved comments."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        commit_comments = pull_request.commit_comments
        messages = []

        for comment in commit_comments:
            if not comment["is_resolved"]:
                messages.append(
                    f"{cls.description()} {comment['body']} ({comment['url']})"
                )

        return messages


class PullRequestMultipleAuthorsWarning(PullRequestWarning):
    """Pull request has multiple authors."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestMultipleAuthorsWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Pull request has multiple authors."

    @override
    @classmethod
    def run(
        cls,
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
                    for commit in pull_request.commits
                }
            )
            != 1
        ):
            return [cls.description() + " " + cls._authors_str(authors)]

        return []

    @classmethod
    def _authors_str(cls, authors: Iterable[str]) -> str:
        return ", ".join(authors)


ALL_PULL_REQUEST_BLOCKERS = PullRequestBlocker.__subclasses__()
ALL_PULL_REQUEST_WARNINGS = PullRequestWarning.__subclasses__()
ALL_PULL_REQUEST_CHECKS = ALL_PULL_REQUEST_BLOCKERS + ALL_PULL_REQUEST_WARNINGS


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

    def run(self, checks_list: list[str], pull_request: PullRequest) -> list[str]:
        messages = []

        for check in [
            chk for chk in ALL_PULL_REQUEST_CHECKS if chk.name() in checks_list
        ]:
            try:
                if outcome := check.run(pull_request, self._target_repo, self._request):
                    messages.extend(outcome)
            except NotImplementedError:
                messages.append(f"{check.name()} is not implemented")

            except Exception as exc:
                logger.exception(exc)
                messages.append(f"{check.name()} failed to run with error: {exc}")

        return messages
