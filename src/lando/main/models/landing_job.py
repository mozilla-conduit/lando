from __future__ import annotations

import datetime
import enum
import logging
import os
from pathlib import Path
from typing import (
    Any,
    Iterable,
    Optional,
    Self,
)

from django.conf import settings
from django.db import models
from django.db.models import Case, IntegerField, Q, QuerySet, When
from django.utils.translation import gettext_lazy
from mots.config import FileConfig
from mots.directory import Directory

from lando.main.models.base import BaseModel
from lando.main.models.commit_map import CommitMap
from lando.main.models.revision import Revision, RevisionLandingJob
from lando.main.scm.consts import SCM_TYPE_HG

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class JobStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", gettext_lazy("Submitted")
    IN_PROGRESS = "IN_PROGRESS", gettext_lazy("In progress")
    DEFERRED = "DEFERRED", gettext_lazy("Deferred")
    FAILED = "FAILED", gettext_lazy("Failed")
    LANDED = "LANDED", gettext_lazy("Landed")
    CANCELLED = "CANCELLED", gettext_lazy("Cancelled")

    @classmethod
    def ordering(cls) -> Case[Self]:
        """Method for ordering QuerySets by job states.

        For `JobStatus.SUBMITTED` jobs, higher priority items come first
        and then we order by creation time (older first).

        Any `JobStatus.IN_PROGRESS` jobs are second. As there should
        be a maximum of one (per repository), and with the assumption of a single worker
        instance, a worker picking up an IN_PROGRESS job would mean that the job
        previously crashed, and that the worker needs to restart processing.
        """
        return Case(
            When(status=cls.SUBMITTED, then=1),
            When(status=cls.IN_PROGRESS, then=2),
            When(status=cls.DEFERRED, then=3),
            When(status=cls.FAILED, then=4),
            When(status=cls.LANDED, then=5),
            When(status=cls.CANCELLED, then=6),
            default=0,
            output_field=IntegerField(),
        )

    @classmethod
    def pending(cls) -> list[tuple[str, str]]:
        """Group of Job statuses that will change in the future."""
        return [cls.SUBMITTED, cls.IN_PROGRESS, cls.DEFERRED]

    @classmethod
    def final(cls) -> list[tuple[str, str]]:
        """Group of Job statuses that will not change without manual intervention."""
        return [cls.FAILED, cls.LANDED, cls.CANCELLED]


@enum.unique
class JobAction(enum.Enum):
    """Various actions that can be applied to a LandingJob.

    Actions affect the status and other fields on the LandingJob object.
    """

    # Land a job (i.e. success!)
    LAND = "LAND"

    # Defer landing to a later time (i.e. temporarily failed)
    DEFER = "DEFER"

    # A permanent issue occurred and this requires user intervention
    FAIL = "FAIL"

    # A user has requested a cancellation
    CANCEL = "CANCEL"


class LandingJob(BaseModel):
    def __str__(self) -> str:
        return f"LandingJob {self.id} [{self.status}]"

    status = models.CharField(
        max_length=32,
        choices=JobStatus,
        default=None,
        null=True,  # TODO: should change this to not-nullable
        blank=True,
        db_index=True,
    )

    # revision_to_diff_id and revision_order are deprecated and kept for historical reasons.
    revision_to_diff_id = models.JSONField(null=True, blank=True, default=dict)
    revision_order = models.JSONField(null=True, blank=True, default=dict)

    # Text describing errors when status != LANDED.
    error = models.TextField(default="", blank=True)

    # Error details in a dictionary format, listing failed merges, etc...
    # E.g. {
    #    "failed_paths": [{"path": "...", "url": "..."}],
    #    "rejects_paths": [{"path": "...", "content": "..."}]
    # }
    error_breakdown = models.JSONField(null=True, blank=True, default=dict)

    # LDAP email of the user who requested transplant.
    requester_email = models.CharField(blank=True, default="", max_length=255)

    # Identifier for the most descendent commit created by this landing.
    landed_commit_id = models.TextField(blank=True, default="")

    # Number of attempts made to complete the job.
    attempts = models.IntegerField(default=0)

    # Priority of the job. Higher values are processed first.
    priority = models.IntegerField(default=0)

    # Duration of job from start to finish
    duration_seconds = models.IntegerField(default=0)

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

    # New field in lieu of deprecated repository fields.
    target_repo = models.ForeignKey("Repo", on_delete=models.SET_NULL, null=True)

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
    def landed_treeherder_revision(self) -> str | None:
        """Return a revision suitable for use with TreeStatus.

        At the moment (2025-07-10), Treeherder only supports HgMO as a source of truth,
        so we translate Git commits to their equivalent in HgMO.
        """
        if not self.landed_commit_id:
            return None

        if self.target_repo.scm_type == SCM_TYPE_HG:
            return self.landed_commit_id

        # SCM_TYPE_GIT
        try:
            return CommitMap.git2hg(
                self.target_repo.git_repo_name, self.landed_commit_id
            )
        except CommitMap.DoesNotExist:
            logger.warning(
                f"CommitMap not found for {self.landed_commit_id} in {self.target_repo.name}"
            )

    @property
    def serialized_landing_path(self):  # noqa: ANN201
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

    @classmethod
    def queue_jobs(cls) -> list[dict[str, Any]]:
        """Return an ordered list of queued jobs."""
        jobs = cls.job_queue_query().all()
        return [
            {
                "created_at": j.created_at,
                "id": j.id,
                "url": f"{settings.SITE_URL}/landings/{j.id}",
                "repository": j.target_repo.short_name,
                "requester": j.requester_email,
                "revisions": [
                    f"{settings.PHABRICATOR_URL}/D{r.revision_id}" for r in j.revisions
                ],
                "status": j.status,
                "updated_at": j.updated_at,
            }
            for j in jobs
        ]

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
        q = cls.objects.filter(status__in=JobStatus.pending())

        if repositories:
            q = q.filter(target_repo__in=repositories)

        if grace_seconds:
            now = datetime.datetime.now(datetime.timezone.utc)
            grace_cutoff = now - datetime.timedelta(seconds=grace_seconds)
            q = q.filter(created_at__lt=grace_cutoff)

        q = q.annotate(status_order=JobStatus.ordering()).order_by(
            "-status_order", "-priority", "created_at"
        )

        return q

    @classmethod
    def next_job(cls, repositories: Optional[Iterable[str]] = None) -> QuerySet:
        """Return a query which selects the next job and locks the row."""
        query = cls.job_queue_query(repositories=repositories)

        # Returned rows should be locked for updating, this ensures the next
        # job can be claimed.
        return query.select_for_update()

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
    def revisions(self):  # noqa: ANN201
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

    def transition_status(
        self,
        action: JobAction,
        **kwargs,
    ):
        """Change the status and other applicable fields according to actions.

        Args:
            action (JobAction): the action to take, e.g. "land" or "fail"
            **kwargs:
                Additional arguments required by each action, e.g. `message` or
                `commit_id`.
        """
        actions = {
            JobAction.LAND: {
                "required_params": ["commit_id"],
                "status": JobStatus.LANDED,
            },
            JobAction.FAIL: {
                "required_params": ["message"],
                "status": JobStatus.FAILED,
            },
            JobAction.DEFER: {
                "required_params": ["message"],
                "status": JobStatus.DEFERRED,
            },
            JobAction.CANCEL: {
                "required_params": [],
                "status": JobStatus.CANCELLED,
            },
        }

        if action not in actions:
            raise ValueError(f"{action} is not a valid action")

        required_params = actions[action]["required_params"]
        if sorted(required_params) != sorted(kwargs.keys()):
            missing_params = required_params - kwargs.keys()
            raise ValueError(f"Missing {missing_params} params")

        self.status = actions[action]["status"]

        if action in (JobAction.FAIL, JobAction.DEFER):
            self.error = kwargs["message"]

        if action == JobAction.LAND:
            self.landed_commit_id = kwargs["commit_id"]

        self.save()


def add_job_with_revisions(
    revisions: list[Revision],
    **params: Any,  # noqa: ANN401
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
