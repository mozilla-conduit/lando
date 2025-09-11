from django.db import models

from lando.main.models import (
    BaseJob,
    BaseModel,
)


class TryJob(BaseJob):
    """Represent a Try job."""

    type = "Try"

    target_commit_hash = models.TextField(blank=True, default="")


class TryAction(BaseModel):
    job_id = models.ForeignKey(TryJob, on_delete=models.CASCADE, related_name="actions")

    # Data for each individual action. Data in these fields should be
    # parsable into the appropriate Pydantic schema.
    data = models.JSONField()

    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
