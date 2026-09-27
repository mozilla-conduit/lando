"""This file contains lando-specific GitHub logic."""

import functools
import io
import json
import math
from collections.abc import Callable
from datetime import datetime
from json.decoder import JSONDecodeError
from typing import Self

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.views import View
from typing_extensions import override

from lando.api.legacy.bmo import BugFetchError, fetch_bugs
from lando.api.legacy.commit_message import parse_bugs
from lando.main.scm.helpers import PatchHelper, PatchHelperMetadata
from lando.utils.github import PullRequest


class LandoPullRequest(PullRequest):
    """A PullRequest object with additional Lando-specific logic.

    This object extends on the `github.PullRequest` by adding additional behaviours which
    is not strictly GitHub-related and/or are provided by other modules in Lando.
    """

    @classmethod
    def from_pr(cls, pr: PullRequest) -> Self:
        """Build a LandoPullRequest from a PullRequest.

        This allows to obtain a `LandoPullRequest` without having to rebuild it from
        scratch. This is useful, particularly if the source `PullRequest` was provided by
        a factory, e.g., `GitHubAPIClient.build_pull_request`:


            client = GitHubAPIClient(target_repo.url)
            pull_request = LandoPullRequest.from_pr(
                client.build_pull_request(pull_number)
            )
        """
        return cls(pr.client, pr._data)

    @property
    def bug_ids(self) -> set[int]:
        """The set of Bugzilla bug numbers referenced by the PR's commit messages."""
        bug_ids: set[int] = set()
        for commit in self.commits:
            bug_ids.update(parse_bugs(commit["commit"]["message"]))
        return bug_ids

    @functools.cached_property
    def bugs_by_id(self) -> dict[int, dict] | None:
        """BMO bug data for the PR's referenced bugs, keyed by id (`None` on failure)."""
        try:
            return fetch_bugs(self.bug_ids)
        except BugFetchError:
            return None


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
        """Create a PullRequestPatchHelper from a PullRequest.

        Note: as this class doesn't currently use any logic introduced by the
        LandoPullRequest, it is built around a simple PullRequest. While object
        inheritance allows to build this patch helper with either PR class, the
        superclass is sufficient.
        """
        super().__init__()

        self._pr = pr

        self._diff = pr.diff

        author_name, author_email = self._pr.author

        self.headers = {
            "date": self._get_timestamp_from_github_timestamp(pr.updated_at),
            "from": f"{author_name} <{author_email}>",
            "subject": pr.title,
        }

        self.metadata = PatchHelperMetadata()

    @classmethod
    def _get_timestamp_from_github_timestamp(cls, timestamp: str) -> str:
        timestamp_datetime = datetime.fromisoformat(timestamp)
        return str(math.floor(timestamp_datetime.timestamp()))

    @classmethod
    @override
    def from_string_io(cls, string_io: io.StringIO) -> "PatchHelper":
        """Implement the PatchHelper interface; not relevant for GitHub PRs."""
        raise NotImplementedError("`from_string_io` not implemented.")

    @classmethod
    @override
    def from_bytes_io(cls, bytes_io: io.BytesIO) -> "PatchHelper":
        """Implement the PatchHelper interface; not relevant for GitHub PRs."""
        raise NotImplementedError("`from_bytes_io` not implemented.")

    def get_commit_description(self) -> str:
        """Return the full commit description."""
        # We can't use pr.commit_message here,
        # as it also appends a trailer with the PR URL.
        lines = [self._pr.title]

        if self._pr.commit_body:
            lines += ["", self._pr.commit_body]

        return "\n".join(lines)

    @override
    def get_diff(self) -> str:
        """Return the patch diff.

        WARNING: As of 2025-10-13, this doesn't include any binary data.
        """
        return self._diff

    @override
    def write(self, f: io.StringIO):
        """Implement the PatchHelper interface; not relevant for GitHub PRs."""
        raise NotImplementedError("`write` not implemented.")

    @override
    def parse_author_information(self) -> tuple[str, str]:
        """Return the author name and email from the patch."""
        return self._pr.author

    @override
    def get_timestamp(self) -> str:
        """Return an `hg export` formatted timestamp."""
        return self.get_header("date")


def ignore_bot_sender(post: Callable) -> Callable:
    """Decorator that drops requests that originate from bots."""

    @functools.wraps(post)
    def _post(view: View, request: WSGIRequest, *args, **kwargs) -> HttpResponse:
        """Drop the request if a bot triggered the original webhook."""
        BOT_SENDER_TYPE = "Bot"
        try:
            sender_type = json.loads(request.body)["sender"]["type"]
        except JSONDecodeError, KeyError, ValueError, TypeError:
            pass
        else:
            if sender_type == BOT_SENDER_TYPE:
                return HttpResponse(status=202)
        return post(view, request, *args, **kwargs)

    return _post
