from __future__ import annotations

import enum
import logging
from typing import Any, Iterable, Optional, Self

from django.contrib import admin
from django.db import models
from django.db.models import Case, IntegerField, QuerySet, When
from django.utils.translation import gettext_lazy

from lando.main.models.base import BaseModel
from lando.main.models.commit_map import CommitMap
from lando.main.models.repo import Repo
from lando.main.scm.consts import SCM_TYPE_HG

logger = logging.getLogger(__name__)


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
        """Group of Job statuses that may change in the future.

        This includes IN_PROGRESS jobs. See doc for ordering().
        """
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


class BaseJob(BaseModel):
    """A base job model, for things that get processed by workers."""

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.__class__.__name__} {self.id} [{self.status}]"

    # Current status of the job.
    status = models.CharField(
        max_length=32,
        choices=JobStatus,
        default=None,
        null=True,  # TODO: should change this to not-nullable
        blank=True,
        db_index=True,
    )
    # Text describing errors when status != LANDED.
    error = models.TextField(default="", blank=True)

    # Identifier for the most descendent commit created by this landing.
    landed_commit_id = models.TextField(blank=True, default="")

    # LDAP email of the user who created the job.
    requester_email = models.CharField(blank=True, default="", max_length=255)

    # Number of attempts made to complete the job.
    attempts = models.IntegerField(default=0)

    # Priority of the job. Higher values are processed first.
    priority = models.IntegerField(default=0)

    # Duration of job from start to finish
    duration_seconds = models.IntegerField(default=0)

    # Reference to the target repo.
    target_repo = models.ForeignKey(Repo, on_delete=models.SET_NULL, null=True)

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

    @classmethod
    def next_job(
        cls,
        repositories: Optional[Iterable[str]] = None,
        **kwargs,
    ) -> QuerySet:
        """Return a query which selects the next job and locks the row."""

        query = cls.job_queue_query(repositories=repositories, **kwargs)

        # Returned rows should be locked for updating, this ensures the next
        # job can be claimed.
        return query.select_for_update()

    @classmethod
    def queue_jobs(cls) -> list[dict[str, Any]]:
        """Return an ordered list of queued jobs."""
        jobs = cls.job_queue_query().all()
        return [j.to_dict() for j in jobs]

    @classmethod
    def job_queue_query(
        cls, repositories: Optional[Iterable[str]] = None, **kwargs
    ) -> QuerySet:
        """Return a query which selects the queued jobs.

        The default implementation includes IN_PROGRESS jobs. See doc for ordering().

        Args:
            repositories (iterable): A list of repository names to use when filtering
                the landing job search query.

            **kwargs (dict): Additional arguments for descendent classes.
        """
        q = cls.objects.filter(status__in=JobStatus.pending())

        if repositories:
            q = q.filter(target_repo__in=repositories)

        q = q.annotate(status_order=JobStatus.ordering()).order_by(
            "-status_order", "-priority", "created_at"
        )

        return q

    def to_dict(self) -> dict[str, Any]:
        """Return the job details as a dict."""
        job_dict = {
            "created_at": self.created_at,
            "error": self.error,
            "id": self.id,
            "requester": self.requester_email,
            "status": self.status,
            "updated_at": self.updated_at,
        }

        if self.target_repo:
            job_dict["repository"] = (self.target_repo.short_name,)

        return job_dict


class JobAdmin(admin.ModelAdmin):
    """A base admin class for jobs."""

    list_display = (
        "id",
        "status",
        "target_repo__name",
        "created_at",
        "requester_email",
        "duration_seconds",
    )
    list_filter = ("target_repo__name", "requester_email", "created_at")
    readonly_fields = (
        "attempts",
        "duration_seconds",
        "error",
        "landed_commit_id",
        "requester_email",
    )
