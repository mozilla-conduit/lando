import json
from typing import Any
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse

from lando.main.models import BaseModel
from lando.main.models.jobs import BaseJob, JobStatus
from lando.main.models.revision import Revision

# Yes/No constants for re-use in `TextChoices`, since `Enum`
# can't be subclassed.
YES = "yes", "Yes"
NO = "no", "No"


class YesNoChoices(models.TextChoices):
    """A yes/no choice selection."""

    YES = YES
    NO = NO


class YesNoUnknownChoices(models.TextChoices):
    """A yes/no/unknown choice selection."""

    YES = YES
    NO = NO
    UNKNOWN = "unknown", "Unknown"


class LowMediumHighChoices(models.TextChoices):
    """A low/medium/high choice selection."""

    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class UpliftAssessment(BaseModel):
    """Represents the responses to the uplift request form."""

    # User who submitted the form.
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)

    # User impact if declined?
    user_impact = models.TextField(blank=False)

    # Code covered by automated testing?
    covered_by_testing = models.CharField(
        blank=False,
        choices=YesNoUnknownChoices.choices,
        max_length=8,
        # Default selection in the associated form.
        default=YesNoUnknownChoices.YES,
    )

    # Fix verified in Nightly.
    fix_verified_in_nightly = models.CharField(
        blank=False,
        choices=YesNoChoices.choices,
        max_length=3,
        # Default selection in the associated form.
        default=YesNoChoices.YES,
    )

    # Needs manual QE test.
    needs_manual_qe_testing = models.CharField(
        blank=False,
        choices=YesNoChoices.choices,
        max_length=3,
        # Default selection in the associated form.
        default=YesNoChoices.YES,
    )

    # Steps to reproduce for manual QE testing.
    qe_testing_reproduction_steps = models.TextField(blank=True)

    # Risk associated with taking this patch.
    risk_associated_with_patch = models.CharField(
        blank=False,
        choices=LowMediumHighChoices.choices,
        max_length=6,
        # Default selection in the associated form.
        default=LowMediumHighChoices.LOW,
    )

    # Explanation of risk level.
    risk_level_explanation = models.TextField(blank=False)

    # String changes made/needed?
    string_changes = models.TextField(blank=False)

    # Is Android affected?
    is_android_affected = models.CharField(
        blank=False,
        choices=YesNoUnknownChoices.choices,
        max_length=8,
        # Default selection in the associated form.
        default=YesNoUnknownChoices.YES,
    )

    def to_conduit_json(self) -> dict[str, Any]:
        """Return the assessment in Conduit API JSON format.

        Convert some fields from text choices to boolean, until the Phabricator
        uplift form is removed.
        """
        return {
            "User impact if declined": self.user_impact,
            "Code covered by automated testing": (
                self.covered_by_testing == YesNoUnknownChoices.YES
            ),
            "Fix verified in Nightly": (
                self.fix_verified_in_nightly == YesNoChoices.YES
            ),
            "Needs manual QE test": self.needs_manual_qe_testing == YesNoChoices.YES,
            "Steps to reproduce for manual QE testing": self.qe_testing_reproduction_steps,
            "Risk associated with taking this patch": self.risk_associated_with_patch,
            "Explanation of risk level": self.risk_level_explanation,
            "String changes made/needed": self.string_changes,
            "Is Android affected?": (
                self.is_android_affected == YesNoUnknownChoices.YES
            ),
        }

    def to_conduit_json_str(self) -> str:
        """Return the assessment as a Conduit API JSON string."""
        return json.dumps(self.to_conduit_json())


class UpliftRevision(BaseModel):
    """Link an uplift request form to a revision."""

    assessment = models.ForeignKey(
        UpliftAssessment, on_delete=models.CASCADE, related_name="revisions"
    )

    # Phabricator revision ID, ie `1234` for `D1234`.
    revision_id = models.IntegerField(blank=True, null=True, unique=True)

    class Meta:
        unique_together = ("assessment", "revision_id")


class UpliftSubmission(BaseModel):
    """Represents a single uplift submission.

    Ties together all associated uplift jobs and the uplift request assessment form.
    """

    # User who requested the uplift.
    requested_by = models.ForeignKey(User, on_delete=models.DO_NOTHING)

    # The revision Phabricator IDs to be uplifted.
    requested_revision_ids = models.JSONField(default=list)

    assessment = models.ForeignKey(
        UpliftAssessment,
        on_delete=models.PROTECT,
        related_name="uplift_submission",
    )


class RevisionUpliftJob(BaseModel):
    """Through model to map revisions to uplift jobs."""

    uplift_job = models.ForeignKey("UpliftJob", on_delete=models.SET_NULL, null=True)
    revision = models.ForeignKey(Revision, on_delete=models.SET_NULL, null=True)
    index = models.IntegerField(null=True, blank=True)


class UpliftJob(BaseJob):
    """Represents an uplift job against a single train.

    Most of the data is derived from `BaseJob`, with the extra content residing in
    the associated `UpliftSubmission`.
    """

    type: str = "Uplift"

    # Store the created revision ID for the job on success.
    created_revision_ids = models.JSONField(default=list, blank=True)

    # Error details in a dictionary format, listing failed merges, etc...
    # E.g. {
    #    "failed_paths": [{"path": "...", "url": "..."}],
    #    "rejects_paths": [{"path": "...", "content": "..."}]
    # }
    error_breakdown = models.JSONField(null=True, blank=True, default=dict)

    submission = models.ForeignKey(
        UpliftSubmission, on_delete=models.DO_NOTHING, related_name="uplift_jobs"
    )

    unsorted_revisions = models.ManyToManyField(
        Revision, through=RevisionUpliftJob, related_name="uplift_jobs"
    )

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
            RevisionUpliftJob.objects.filter(revision=revision, uplift_job=self).update(
                index=index
            )

    @property
    def revisions(self) -> models.QuerySet:
        """Return and ordered list of revisions for this job."""
        return self.unsorted_revisions.all().order_by("revisionupliftjob__index")

    def url(self) -> str:
        """Return a URL for this job."""
        return urljoin(settings.SITE_URL, reverse("uplift-jobs-page", args=[self.id]))

    @property
    def has_created_revisions(self) -> bool:
        """Return True when the job landed and recorded created revisions."""
        try:
            status = JobStatus(self.status)
        except ValueError:
            return False
        return status == JobStatus.LANDED and bool(self.created_revision_ids)
