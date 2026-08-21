import logging
from abc import ABC, abstractmethod
from typing import Iterable

from django.http import HttpRequest
from typing_extensions import override

from lando.api.legacy.bmo import (
    missing_status_flags_message,
    security_keyword,
    unset_status_flags,
    unverified_status_flags_message,
)
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
        """Inspect the PR for an issue, and return a message string if present."""


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
        return (
            "Revision makes changes to data collection and should "
            "have its data classification assessed before landing. "
        )

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


# GITHUB-SPECIFIC CHECKS


class PullRequestBaseBranchDoesNotMatchTree(PullRequestBlocker):
    """The base branch for this PR doesn't match this Tree."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestBaseBranchDoesNotMatchTree"

    @override
    @classmethod
    def description(cls) -> str:
        return "The base branch for this PR doesn't match this Tree."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.base_ref != target_repo.default_branch:
            return [cls.description()]

        return []


class PullRequestConflictWithBaseBranch(PullRequestBlocker):
    """This Pull Request has conflicts that must be resolved."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestConflictWithBaseBranch"

    @override
    @classmethod
    def description(cls) -> str:
        return "This Pull Request has conflicts that must be resolved."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        if pull_request.mergeable_state == pull_request.Mergeability.DIRTY:
            return [cls.description()]

        return []


class PullRequestFailingCheck(PullRequestBlocker):
    """This Pull Request has some failing checks."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestFailingCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "This Pull Request has some failing checks."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # If we need more details on which tests are failing, we could use the commit
        # statuses endpoint instead [0].
        #
        # [0] https://docs.github.com/en/rest/commits/statuses?apiVersion=2022-11-28
        if pull_request.mergeable_state == pull_request.Mergeability.UNSTABLE:
            return [cls.description()]

        return []


class PullRequestSecurityBugStatusFlagsBlocker(PullRequestBlocker):
    """A referenced security bug is missing required status flags."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestSecurityBugStatusFlagsBlocker"

    @override
    @classmethod
    def description(cls) -> str:
        return "A referenced security bug is missing required status flags."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        # Only enforced on repos configured with a status-flag prefix (e.g. Firefox
        # repos with `cf_status_firefox`). See bug 2055604.
        prefix = target_repo.status_flag_prefix
        if not prefix:
            return []

        bugs_by_id = pull_request.bugs_by_id
        if not bugs_by_id:
            # `None` (BMO unavailable) or `{}` (no referenced bugs); the warning
            # check handles anything that could not be verified.
            return []

        messages = []
        for bug_id in sorted(bugs_by_id):
            bug = bugs_by_id[bug_id]
            keyword = security_keyword(bug)
            if keyword is None:
                continue

            missing_flags = unset_status_flags(bug, prefix)
            if missing_flags:
                messages.append(
                    missing_status_flags_message(bug_id, keyword, missing_flags)
                )

        return messages


#
# WARNINGS
#


class PullRequestWarning(PullRequestCheck, ABC):
    """Parent class for warning checks."""


class PullRequestBlockingReviewersWarning(PullRequestWarning):
    """Warn if some requested reviewers or teams haven't provided a review.

    Note: blocking reviewers are warnings by design, as it is expected that users with
    the necessary permission to land (generally SCM3) are trusted to do the right thing.
    """

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestBlockingReviewersWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Is missing reviews from requested reviewers."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        reviewers = pull_request.requested_reviewers
        teams = pull_request.requested_teams

        messages = []

        if reviewers:
            messages.append(
                cls.description() + " Individuals: " + cls._reviewers_str(reviewers)
            )
        if teams:
            messages.append(cls.description() + " Teams: " + cls._teams_str(teams))

        return messages

    @classmethod
    def _reviewers_str(cls, reviewers: Iterable[dict[str, str]]) -> str:
        return ", ".join([r["login"] for r in reviewers])

    @classmethod
    def _teams_str(cls, teams: Iterable[dict[str, str]]) -> str:
        return ", ".join([r["name"] for r in teams])


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
                try:
                    review_title = review["body"].splitlines()[0]
                except IndexError:
                    review_title = "(empty body)"
                messages.append(
                    f"{cls.description()} {review_title}… {review['html_url']})"
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


class PullRequestSecurityBugStatusFlagsUnverifiedWarning(PullRequestWarning):
    """Security bug status flags could not be verified in Bugzilla."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PullRequestSecurityBugStatusFlagsUnverifiedWarning"

    @override
    @classmethod
    def description(cls) -> str:
        return "Security bug status flags could not be verified in Bugzilla."

    @override
    @classmethod
    def run(
        cls,
        pull_request: PullRequest,
        target_repo: Repo,
        request: HttpRequest,
    ) -> list[str]:
        """Warn when status flags for a referenced bug cannot be verified.

        When `PullRequestSecurityBugStatusFlagsBlocker` cannot run — because BMO
        was unavailable, or a referenced bug was absent from the response (e.g. a
        restricted bug Lando's key cannot read) — we degrade to an acknowledgeable
        warning rather than silently allowing the landing.

        Unlike the Phabricator flow, GitHub has no secure-project tag to scope this
        to security revisions, so it warns for any bug referenced by a PR to a
        status-flag repo that could not be verified. All such bugs are collapsed
        into a single message so a BMO outage produces one acknowledgeable warning
        rather than one per referenced bug.
        """
        prefix = target_repo.status_flag_prefix
        if not prefix:
            return []

        bug_ids = pull_request.bug_ids
        if not bug_ids:
            return []

        bugs_by_id = pull_request.bugs_by_id
        if bugs_by_id is None:
            # The whole fetch failed; none of the referenced bugs could be verified.
            unverified = bug_ids
        else:
            unverified = {bug_id for bug_id in bug_ids if bug_id not in bugs_by_id}

        if not unverified:
            return []

        return [unverified_status_flags_message(unverified)]


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
