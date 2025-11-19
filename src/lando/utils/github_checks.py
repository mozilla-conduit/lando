import logging
from abc import ABC, abstractmethod

from django.http import HttpRequest
from typing_extensions import override

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


ALL_PULL_REQUEST_BLOCKERS = PullRequestBlocker.__subclasses__()
ALL_PULL_REQUEST_CHECKS = ALL_PULL_REQUEST_BLOCKERS


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
