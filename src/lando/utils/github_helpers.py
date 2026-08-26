"""This file contains lando-specific GitHub logic."""

import functools
import io
import json
import math
from collections.abc import Callable
from datetime import datetime
from json.decoder import JSONDecodeError

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.views import View
from typing_extensions import override

from lando.main.scm.helpers import PatchHelper, PatchHelperMetadata
from lando.utils.github import PullRequest


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


def ignore_bot_sender(post: Callable) -> Callable:
    """Decorator that drops requests that originate from bots."""

    @functools.wraps(post)
    def _post(view: View, request: WSGIRequest, *args, **kwargs) -> HttpResponse:
        """Drop the request if a bot triggered the original webhook."""
        BOT_SENDER_TYPE = "Bot"
        try:
            sender_type = json.loads(request.body)["sender"]["type"]
        except (JSONDecodeError, KeyError, ValueError, TypeError):
            pass
        else:
            if sender_type == BOT_SENDER_TYPE:
                return HttpResponse(status=202)
        return post(view, request, *args, **kwargs)

    return _post
