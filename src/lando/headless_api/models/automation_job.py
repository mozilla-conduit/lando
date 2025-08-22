from contextlib import contextmanager
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from lando.main.models import (
    BaseJob,
    BaseModel,
    Repo,
)


class AutomationJob(BaseJob):
    """Represent an automation job request through the headless API.

    This job is executed by the automation worker, where the set of associated
    `AutomationAction` entires are retrieved and applied to the target repo locally
    before pushing.
    """

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
        job_dict = self.to_dict()

        # We keep the job_id for backward compatibility with old lando-cli *
        job_dict["job_id"] = job_dict["id"]

        job_dict["message"] = self.status_message
        job_dict["status_url"] = self.status_url

        return job_dict

    @property
    def status_url(self) -> str:
        return f"{settings.SITE_URL}/api/job/{self.id}"

    @property
    def status_message(self) -> str:
        return f"Job is in the {self.status} state."

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
