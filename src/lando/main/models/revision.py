"""
This module provides the definitions for custom revision/diff warnings.

The `DiffWarning` model provides a warning that is associated with a particular
Phabricator diff that is associated with a particular revision.
"""

from __future__ import annotations

import logging
import re
from io import StringIO
from typing import Any, Optional

from django.db import models
from django.utils.translation import gettext_lazy

from lando.api.legacy.hgexports import HgPatchHelper
from lando.main.models.base import BaseModel
from lando.main.scm.exceptions import NoDiffStartLine
from lando.utils import build_patch_for_revision

logger = logging.getLogger(__name__)


class RevisionLandingJob(BaseModel):
    landing_job = models.ForeignKey("LandingJob", on_delete=models.SET_NULL, null=True)
    revision = models.ForeignKey("Revision", on_delete=models.SET_NULL, null=True)
    index = models.IntegerField(null=True, blank=True)
    diff_id = models.IntegerField(null=True, blank=True)


class Revision(BaseModel):
    """
    A representation of a revision in the database.

    Includes a reference to the related Phabricator revision and diff ID if one exists.
    """

    # revision_id and diff_id map to Phabricator IDs (integers).
    revision_id = models.IntegerField(blank=True, null=True, unique=True)

    # diff_id is that of the latest diff on the revision at landing request time. It
    # does not track all diffs.
    diff_id = models.IntegerField(blank=True, null=True)

    # The actual patch with Mercurial metadata format.
    patch = models.TextField(blank=True, default="")

    # Patch metadata, such as
    # - author_name
    # - author_email
    # - commit_message
    # - timestamp
    # - ...
    patch_data = models.JSONField(blank=True, default=dict)

    # A general purpose data field to store arbitrary information about this revision.
    data = models.JSONField(blank=True, default=dict)

    # The commit ID generated by the landing worker, before pushing to remote repo.
    commit_id = models.CharField(max_length=40, null=True, blank=True)

    _patch_helper: Optional[HgPatchHelper] = None

    def __str__(self):
        return f"Revision {self.revision_id} Diff {self.diff_id}"

    def __repr__(self) -> str:
        """Return a human-readable representation of the instance."""
        # Add an identifier for the Phabricator revision if it exists.
        phab_identifier = (
            f" [D{self.revision_id}-{self.diff_id}]>" if self.revision_id else ""
        )
        return f"<{self.__class__.__name__}: {self.id}{phab_identifier}>"

    @property
    def patch_bytes(self) -> bytes:
        return self.patch.encode("utf-8")

    @classmethod
    def get_from_revision_id(cls, revision_id: int) -> "Revision" | None:
        """Return a Revision object from a given ID."""
        if cls.objects.filter(revision_id=revision_id).exists():
            return cls.objects.get(revision_id=revision_id)

    @classmethod
    def new_from_patch(cls, raw_diff: str, patch_data: dict[str, str]) -> Revision:
        """Construct a new Revision from patch data.

        `patch_data` is expected to contain the following keys:
            - author_name
            - author_email
            - commit_message
            - timestamp (unix timestamp as a string)
        """
        rev = Revision()
        rev.set_patch(raw_diff, patch_data)
        rev.save()
        return rev

    def set_patch(self, raw_diff: str, patch_data: dict[str, str]):
        """Given a raw_diff and patch data, build the patch and store it."""
        self.patch_data = patch_data
        patch = build_patch_for_revision(raw_diff, **self.patch_data)
        self.patch = patch

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "revision_id": self.revision_id,
            "diff_id": self.diff_id,
            "landing_jobs": [job.id for job in self.landing_jobs.all()],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def author(self):
        """Get the full author string in "Name <Email>" format."""
        parts = []
        if self.author_name:
            parts.append(self.author_name)
        if self.author_email:
            parts.append(f"<{self.author_email}>")

        return " ".join(parts)

    @property
    def author_name(self) -> Optional[str]:
        return self.metadata.get("author_name")

    @property
    def author_email(self) -> Optional[str]:
        return self.metadata.get("author_email")

    @property
    def commit_message(self) -> Optional[str]:
        return self.metadata.get("commit_message")

    @property
    def timestamp(self) -> Optional[str]:
        if ts := self.metadata.get("timestamp"):
            # Some codepaths (via Phabricator) have the timestamp set as an int.
            # We make sure it's always a string.
            return str(ts)
        return None

    @property
    def metadata(self) -> dict[str, str]:
        """Parse Hg metadata out of the raw patch, and update the patch_data if empty."""
        if not self.patch_data:
            commit_message = self.patch_helper.get_commit_description()
            author_name, author_email = self._parse_author_string(
                self.patch_helper.get_header("User")
            )
            timestamp = self.patch_helper.get_timestamp()

            self.patch_data = {"commit_message": commit_message, "timestamp": timestamp}
            if author_name:
                self.patch_data["author_name"] = author_name
            if author_email:
                self.patch_data["author_email"] = author_email

        return self.patch_data

    @staticmethod
    def _parse_author_string(author: str) -> tuple[str, str]:
        """Parse a Git author string into author name and email.

        The returned tuple will have the empty string "" for unmatched parts.
        """
        r = re.compile(
            r"^(?P<author_name>.*?)? *<?(?P<author_email>[^ \t\n\r\f\v<]+@[^ \t\n\r\f\v>]+)>?"
        )
        m = r.match(author)
        if not m:
            return (author, "")
        return m.groups()

    @property
    def diff(self) -> str:
        """Return the unified diff text without any metadata"""
        # The HgPatchHelper currently returns leading newline, which we don't want to
        # return here, so we strip it.
        return self.patch_helper.get_diff().lstrip()

    @property
    def patch_helper(self) -> HgPatchHelper:
        """Create and cache an HgPatchHelper to parse the raw patch with Hg metadata."""
        if not self._patch_helper:
            self._patch_helper = HgPatchHelper(StringIO(self.patch))
            if not self._patch_helper.diff_start_line:
                raise NoDiffStartLine

        return self._patch_helper


class DiffWarningStatus(models.TextChoices):
    ACTIVE = "ACTIVE", gettext_lazy("Active")
    ARCHIVED = "ARCHIVED", gettext_lazy("Archived")


class DiffWarningGroup(models.TextChoices):
    GENERAL = "GENERAL", gettext_lazy("General")
    LINT = "LINT", gettext_lazy("Lint")


class DiffWarning(BaseModel):
    """Represents a warning message associated with a particular diff and revision."""

    # A Phabricator revision and diff ID (NOTE: revision ID does not include a prefix.)
    revision_id = models.IntegerField()
    diff_id = models.IntegerField()

    # An arbitary dictionary of data that will be determined by the client.
    # It is up to the UI to interpret this data and show it to the user.
    error_breakdown = models.JSONField(null=False, blank=True, default=dict)

    # Whether the warning is active or archived. This is used in filters.
    status = models.CharField(
        max_length=12,
        choices=DiffWarningStatus,
        default=DiffWarningStatus.ACTIVE,
        null=False,
        blank=True,
    )

    # The "type" of warning. This is mainly to group warnings when querying the API.
    group = models.CharField(
        max_length=12,
        choices=DiffWarningGroup,
        null=False,
        blank=False,
    )

    def serialize(self):
        """Return a JSON serializable dictionary."""
        return {
            "id": self.id,
            "diff_id": self.diff_id,
            "revision_id": self.revision_id,
            "status": self.status.value,
            "group": self.group.value,
            "data": self.data,
        }
