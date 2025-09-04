from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
from typing import (
    Any,
    Iterable,
    Optional,
)

from django.conf import settings
from django.db import models
from django.db.models import Q, QuerySet
from mots.config import FileConfig
from mots.directory import Directory

from lando.main.models.jobs import BaseJob
from lando.main.models.revision import Revision, RevisionLandingJob

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class LandingJob(BaseJob):
    """A landing job for Phabricator revisions."""

    type: str = "Landing"

    # revision_to_diff_id and revision_order are deprecated and kept for historical reasons.
    revision_to_diff_id = models.JSONField(null=True, blank=True, default=dict)
    revision_order = models.JSONField(null=True, blank=True, default=dict)

    # Error details in a dictionary format, listing failed merges, etc...
    # E.g. {
    #    "failed_paths": [{"path": "...", "url": "..."}],
    #    "rejects_paths": [{"path": "...", "content": "..."}]
    # }
    error_breakdown = models.JSONField(null=True, blank=True, default=dict)

    # JSON array of changeset hashes which replaced reviewed changesets
    # after autoformatting.
    # eg.
    #    ["", ""]
    formatted_replacements = models.JSONField(null=True, blank=True, default=None)

    # Identifier of the published commit which this job should land on top of.
    target_commit_hash = models.TextField(blank=True, default="")

    unsorted_revisions = models.ManyToManyField(
        Revision, through="RevisionLandingJob", related_name="landing_jobs"
    )

    @property
    def landed_revisions(self) -> dict:
        """Return revision and diff ID mapping associated with the landing job."""
        revision_ids = [revision.id for revision in self.unsorted_revisions.all()]
        revision_landing_jobs = (
            RevisionLandingJob.objects.filter(
                revision__id__in=revision_ids,
                landing_job=self,
            )
            .order_by("index")
            .values_list("revision__revision_id", "diff_id")
        )
        return dict(revision_landing_jobs)

    @property
    def serialized_landing_path(self) -> list[dict]:
        """Return landing path based on associated revisions or legacy fields."""
        if self.unsorted_revisions:
            return [
                {
                    "revision_id": "D{}".format(revision_id),
                    "diff_id": diff_id,
                }
                for revision_id, diff_id in self.landed_revisions.items()
            ]
        else:
            return [
                {"revision_id": "D{}".format(r), "diff_id": self.revision_to_diff_id[r]}
                for r in self.revision_order
            ]

    @property
    def landing_job_identifier(self) -> str:
        """Human-readable representation of the branch head.

        Returns a Phabricator revision ID if the revisions are associated with a Phabricator
        repo, otherwise the first line of the commit message.
        """
        if not self.unsorted_revisions.exists():
            raise ValueError(
                "Job must be associated with a revision to have a relevant identifier."
            )

        head = self.unsorted_revisions.order_by("id").first()
        if head.revision_id:
            # Return the Phabricator identifier if the head revision has one.
            return f"D{head.revision_id}"

        # If there is no Phabricator identifier, return the first line of the
        # non-try-syntax commit's message for the patch.
        if self.unsorted_revisions.count() > 1:
            head = self.unsorted_revisions.order_by("-id")[1]

        commit_message = head.patch_data.get("commit_message")
        if commit_message:
            return f"try push with tip commit '{commit_message.splitlines()[0]}'"

        # Return a placeholder in the event neither exists.
        return "unknown"

    @classmethod
    def revisions_query(cls, revisions: Iterable[str]) -> QuerySet:
        """
        Return all landing jobs associated with a given list of revisions.

        Older records do not have associated revisions, but rather have a JSONB field
        that stores revisions and diff IDs. Those records are now deprecated and will
        not be included in this query.
        """
        revisions = [str(int(r)) for r in revisions]
        return cls.objects.filter(
            Q(unsorted_revisions__revision_id__in=revisions)
            | Q(revision_to_diff_id__has_keys=revisions)
        ).distinct()

    def to_dict(self) -> dict[str, Any]:
        job_dict = super().to_dict()
        job_dict["revisions"] = [
            f"{settings.PHABRICATOR_URL}/D{r.revision_id}" for r in self.revisions
        ]
        job_dict["url"] = f"{settings.SITE_URL}/landings/{self.id}"

        return job_dict

    @classmethod
    def job_queue_query(
        cls,
        repositories: Optional[Iterable[str]] = None,
        grace_seconds: int = DEFAULT_GRACE_SECONDS,
        **kwargs,
    ) -> QuerySet:
        """Return a query which selects the queued jobs.

        Args:
            repositories (iterable): A list of repository names to use when filtering
                the landing job search query.
            grace_seconds (int): Ignore landing jobs that were submitted after this
                many seconds ago.
        """
        q = super().job_queue_query(repositories)

        if grace_seconds:
            now = datetime.datetime.now(datetime.timezone.utc)
            grace_cutoff = now - datetime.timedelta(seconds=grace_seconds)
            q = q.filter(created_at__lt=grace_cutoff)

        return q

    def add_revisions(self, revisions: list[Revision]):
        """Associate a list of revisions with job."""
        for revision in revisions:
            self.unsorted_revisions.add(revision)

    def sort_revisions(self, revisions: list[Revision]):
        """Sort the associated revisions based on provided list."""
        if len(revisions) != len(self.unsorted_revisions.all()):
            raise ValueError("List of revisions does not match associated revisions")

        # Update association table records with correct index values.
        for index, revision in enumerate(revisions):
            RevisionLandingJob.objects.filter(
                revision=revision, landing_job=self
            ).update(index=index)

    @property
    def revisions(self) -> QuerySet:
        return self.unsorted_revisions.all().order_by("revisionlandingjob__index")

    def set_landed_revision_diffs(self):
        """Assign diff_ids, if available, to each association row."""
        # Update association table records with current diff_id values.
        for revision in self.unsorted_revisions.all():
            RevisionLandingJob.objects.filter(
                revision=revision, landing_job=self
            ).update(diff_id=revision.diff_id)

    def set_landed_reviewers(self, path: Path):
        """Set approving peers and owners at time of landing."""
        directory = Directory(FileConfig(path))
        for revision in self.unsorted_revisions.all():
            approved_by = revision.data.get("approved_by")
            if not approved_by:
                continue

            if "peers_and_owners" not in revision.data:
                revision.data["peers_and_owners"] = []

            for reviewer in approved_by:
                if (
                    reviewer in directory.peers_and_owners
                    and reviewer not in revision.data["peers_and_owners"]
                ):
                    revision.data["peers_and_owners"].append(reviewer)

            revision.save()


def add_job_with_revisions(
    revisions: list[Revision],
    **params,
) -> LandingJob:
    """Creates a new job and associates provided revisions with it."""
    job = LandingJob(**params)
    # We need to save the job prior to adding revisions, so the PKs can be linked.
    job.save()
    add_revisions_to_job(revisions, job)
    job.save()
    return job


def add_revisions_to_job(revisions: list[Revision], job: LandingJob):
    """Given an existing job, add and sort provided revisions."""
    job.add_revisions(revisions)
    job.sort_revisions(revisions)
