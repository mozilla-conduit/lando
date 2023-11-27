from __future__ import annotations

import datetime
import logging
import os
from typing import (
    Any,
    Iterable,
    Optional,
)

from django.db import models
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy

from lando.utils import build_patch_for_revision

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class LandingJobStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", gettext_lazy("Submitted")
    IN_PROGRESS = "IN_PROGRESS", gettext_lazy("In progress")
    DEFERRED = "DEFERRED", gettext_lazy("Deferred")
    FAILED = "FAILED", gettext_lazy("Failed")
    LANDED = "LANDED", gettext_lazy("Landed")
    CANCELLED = "CANCELLED", gettext_lazy("Cancelled")


class Revision(BaseModel):
    """
    A representation of a revision in the database.

    Includes a reference to the related Phabricator revision and diff ID if one exists.
    """

    # revision_id and diff_id map to Phabricator IDs (integers).
    revision_id = models.IntegerField(null=True, unique=True)

    # diff_id is that of the latest diff on the revision at landing request time. It
    # does not track all diffs.
    diff_id = models.IntegerField(null=True)

    # The actual patch.
    patch_bytes = models.BinaryField(default=b"")

    # Patch metadata, such as author, timestamp, etc...
    patch_data = models.JSONField(default=dict)

    # A general purpose data field to store arbitrary information about this revision.
    data = models.JSONField(default=dict)

    def __repr__(self) -> str:
        """Return a human-readable representation of the instance."""
        # Add an identifier for the Phabricator revision if it exists.
        phab_identifier = (
            f" [D{self.revision_id}-{self.diff_id}]>" if self.revision_id else ""
        )
        return f"<{self.__class__.__name__}: {self.id}{phab_identifier}>"

    @property
    def patch_string(self) -> str:
        """Return the patch as a UTF-8 encoded string."""
        return self.patch_bytes.decode("utf-8")

    def set_patch(self, raw_diff: str, patch_data: dict[str, str]):
        """Given a raw_diff and patch data, build the patch and store it."""
        self.patch_data = patch_data
        patch = build_patch_for_revision(raw_diff, **self.patch_data)
        self.patch_bytes = patch.encode("utf-8")


class LandingJob(BaseModel):
    status = models.CharField(
        max_length=12,
        choices=LandingJobStatus,
        default=None,
        null=True,  # TODO: should change this to not-nullable
        blank=True,
    )

    # Text describing errors when status != LANDED.
    error = models.TextField(default="", blank=True)

    # Error details in a dictionary format, listing failed merges, etc...
    # E.g. {
    #    "failed_paths": [{"path": "...", "url": "..."}],
    #    "reject_paths": [{"path": "...", "content": "..."}]
    # }
    error_breakdown = models.JSONField(null=True, blank=True, default=dict)

    # LDAP email of the user who requested transplant.
    requester_email = models.CharField(max_length=255)

    # Lando's name for the repository.
    repository_name = models.CharField(max_length=255)

    # URL of the repository revisions are to land to.
    repository_url = models.TextField(default="")

    # Identifier for the most descendent commit created by this landing.
    landed_commit_id = models.TextField(default="")

    # Number of attempts made to complete the job.
    attempts = models.IntegerField(default=0)

    # Priority of the job. Higher values are processed first.
    priority = models.IntegerField(default=0)

    # Duration of job from start to finish
    duration_seconds = models.IntegerField(default=0)

    # Identifier of the published commit which this job should land on top of.
    target_commit_hash = models.TextField(default="")

    revisions = models.ManyToManyField(Revision)  # TODO: order by index

    @classmethod
    def job_queue_query(
        cls,
        repositories: Optional[Iterable[str]] = None,
        grace_seconds: int = DEFAULT_GRACE_SECONDS,
    ) -> QuerySet:
        """Return a query which selects the queued jobs.

        Args:
            repositories (iterable): A list of repository names to use when filtering
                the landing job search query.
            grace_seconds (int): Ignore landing jobs that were submitted after this
                many seconds ago.
        """
        applicable_statuses = (
            cls.LandingJobStatus.SUBMITTED,
            cls.LandingJobStatus.IN_PROGRESS,
            cls.LandingJobStatus.DEFERRED,
        )
        q = cls.objects.filter(status__in=applicable_statuses)

        if repositories:
            q = q.filter(repository_name__in=(repositories))

        if grace_seconds:
            now = datetime.datetime.now(datetime.timezone.utc)
            grace_cutoff = now - datetime.timedelta(seconds=grace_seconds)
            q = q.filter(created_at__lt=grace_cutoff)

        # Any `LandingJobStatus.IN_PROGRESS` job is first and there should
        # be a maximum of one (per repository). For
        # `LandingJobStatus.SUBMITTED` jobs, higher priority items come first
        # and then we order by creation time (older first).
        q = q.order_by("-status", "-priority", "created_at")

        return q

    @classmethod
    def next_job_for_update_query(
        cls, repositories: Optional[Iterable[str]] = None
    ) -> QuerySet:
        """Return a query which selects the next job and locks the row."""
        query = cls.job_queue_query(repositories=repositories)

        # Returned rows should be locked for updating, this ensures the next
        # job can be claimed.
        query = query.select_for_update()

        return query


def add_job_with_revisions(revisions: list[Revision], **params: Any) -> LandingJob:
    """Creates a new job and associates provided revisions with it."""
    job = LandingJob(**params)
    job.save()
    for revision in revisions:
        job.revisions.add(revision)
    return job
