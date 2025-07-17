from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable, Optional, Self

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from lando.main.models.base import BaseModel
from lando.main.models.landing_job import (
    JobAction,
    JobStatus,
)
from lando.main.models.repo import Repo


class AutomationJob(BaseModel):
    """Represent an automation job request through the headless API.

    This job is executed by the automation worker, where the set of associated
    `AutomationAction` entires are retrieved and applied to the target repo locally
    before pushing.
    """

    # Current status of the job.
    status = models.CharField(
        max_length=32,
        choices=JobStatus,
        default=None,
    )

    # Email of the user who created the automation job.
    requester_email = models.CharField(blank=True, default="", max_length=255)

    # Identifier for the most descendent commit created by this landing.
    landed_commit_id = models.TextField(blank=True, default="")

    # Number of attempts made to complete the job.
    attempts = models.IntegerField(default=0)

    # Priority of the job. Higher values are processed first.
    priority = models.IntegerField(default=0)

    # Duration of job from start to finish
    duration_seconds = models.IntegerField(default=0)

    # Reference to the target repo.
    target_repo = models.ForeignKey(Repo, on_delete=models.SET_NULL, null=True)

    # Text describing errors when status != LANDED.
    error = models.TextField(default="", blank=True)

    # Name of RelBranch to push changes to.
    relbranch_name = models.CharField(null=True, blank=True)

    # SHA to create RelBranch from, if passed.
    relbranch_commit_sha = models.CharField(null=True, blank=True)

    @contextmanager
    def processing(self):
        """Mutex-like context manager that manages job processing miscellany.

        This context manager facilitates graceful worker shutdown and
        tracks the duration of the current job.
        """
        start_time = datetime.now()
        try:
            yield
        finally:
            self.duration_seconds = (datetime.now() - start_time).seconds
            self.save()

    def to_api_status(self) -> dict[str, Any]:
        """Return the job details as API status JSON."""
        return {
            "job_id": self.id,
            "status_url": f"{settings.SITE_URL}/api/job/{self.id}",
            "message": f"Job is in the {self.status} state.",
            "created_at": self.created_at,
            "status": self.status,
            "error": self.error,
        }

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

    @classmethod
    def next_job(cls, repositories: Optional[Iterable[str]] = None) -> Self:
        """Return the next automation job."""
        return (
            cls.objects.filter(status__in=(JobStatus.SUBMITTED, JobStatus.DEFERRED))
            .filter(target_repo__in=repositories)
            .order_by("-priority", "created_at")
            .select_for_update()
        )

    def resolve_push_target_from_relbranch(self, repo: Repo) -> tuple[str | None, str]:
        """Return (target_cset, push_target) tuple for the `RelBranchSpecifier` if required."""
        if not self.relbranch_name:
            # Without a specifier, don't set a target cset and use the usual
            # push target.
            return None, repo.push_target

        # Push to the RelBranch.
        push_target = self.relbranch_name

        commit_sha = self.relbranch_commit_sha
        if commit_sha:
            # Specify an explicit target cset if passed.
            target_cset = commit_sha
        else:
            # Update to the existing branch head if it exists.
            target_cset = push_target

        return target_cset, push_target

    @property
    def has_one_action(self) -> int:
        return self.actions.count() == 1


class ActionTypeChoices(models.TextChoices):
    """Accepted choices for the types of automation job actions."""

    ADD_COMMIT = "add-commit", gettext_lazy("Add commit")
    ADD_COMMIT_BASE64 = "add-commit-base64", gettext_lazy("Add base64 commit")
    CREATE_COMMIT = "create-commit", gettext_lazy("Create commit")
    TAG = "tag", gettext_lazy("Tag")
    MERGE_ONTO = "merge-onto", gettext_lazy("Merge onto")


class AutomationAction(BaseModel):
    """An action in the automation API."""

    job_id = models.ForeignKey(
        AutomationJob, on_delete=models.CASCADE, related_name="actions"
    )

    action_type = models.CharField(choices=ActionTypeChoices)

    # Data for each individual action. Data in these fields should be
    # parsable into the appropriate Pydantic schema.
    data = models.JSONField()

    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
