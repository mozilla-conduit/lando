from django.db import models

from lando.main.models.base import BaseModel


class AutoformatChange(BaseModel):
    """Record of autoformatting changes applied to a commit during landing."""

    landing_job = models.ForeignKey(
        "LandingJob",
        on_delete=models.CASCADE,
        related_name="autoformat_changes",
    )

    # Commit SHA where autoformatting was applied (amended or new commit).
    commit_sha = models.CharField(max_length=40)

    # File paths modified by autoformatting.
    changed_files = models.JSONField(default=list)

    # Unified diff of the autoformatting changes.
    diff = models.TextField(blank=True, default="")
