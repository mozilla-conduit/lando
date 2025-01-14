from typing import Any

from django.db import models

from lando.main.models.base import BaseModel
from lando.main.models.landing_job import (
    LandingJobAction,
    LandingJobStatus,
)
from lando.main.models.repo import Repo


class AutomationJob(BaseModel):
    """An automation job.

    TODO write better docstring
    """

    # Current status of the job.
    status = models.CharField(
        max_length=32,
        choices=LandingJobStatus,
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

    def to_api_status(self) -> dict[str, Any]:
        """Return the job details as API status JSON.

        TODO make this better?
        """
        return {
            "job_id": self.id,
            "status_url": "TODO",
            "message": f"Job is in the {self.status} state.",
            "created_at": self.created_at,
        }

    def transition_status(
        self,
        action: LandingJobAction,
        **kwargs,
    ):
        """Change the status and other applicable fields according to actions.

        Args:
            action (LandingJobAction): the action to take, e.g. "land" or "fail"
            **kwargs:
                Additional arguments required by each action, e.g. `message` or
                `commit_id`.
        """
        actions = {
            LandingJobAction.LAND: {
                "required_params": ["commit_id"],
                "status": LandingJobStatus.LANDED,
            },
            LandingJobAction.FAIL: {
                "required_params": ["message"],
                "status": LandingJobStatus.FAILED,
            },
            LandingJobAction.DEFER: {
                "required_params": ["message"],
                "status": LandingJobStatus.DEFERRED,
            },
            LandingJobAction.CANCEL: {
                "required_params": [],
                "status": LandingJobStatus.CANCELLED,
            },
        }

        if action not in actions:
            raise ValueError(f"{action} is not a valid action")

        required_params = actions[action]["required_params"]
        if sorted(required_params) != sorted(kwargs.keys()):
            missing_params = required_params - kwargs.keys()
            raise ValueError(f"Missing {missing_params} params")

        self.status = actions[action]["status"]

        if action in (LandingJobAction.FAIL, LandingJobAction.DEFER):
            self.error = kwargs["message"]

        if action == LandingJobAction.LAND:
            self.landed_commit_id = kwargs["commit_id"]

        self.save()


class AutomationAction(BaseModel):
    """An action in the automation API."""

    # TODO should we have `on_delete=models.CASCADE` here?
    job_id = models.ForeignKey(
        AutomationJob, on_delete=models.CASCADE, related_name="actions"
    )

    action_type = models.CharField()

    # Data for each individual action. Data in these fields should be
    # parsable into the appropriate Pydantic schema.
    data = models.JSONField()

    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
