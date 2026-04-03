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

    # Fields to include in conduit JSON output, mapped to their display labels.
    CONDUIT_FIELDS = {
        "user_impact": "User impact if declined/Reason for urgency",
        "covered_by_testing": "Code covered by automated testing?",
        "fix_verified_in_nightly": "Fix verified in Nightly?",
        "needs_manual_qe_testing": "Needs manual QE testing?",
        "qe_testing_reproduction_steps": "Steps to reproduce for manual QE testing",
        "risk_associated_with_patch": "Risk associated with taking this patch",
        "risk_level_explanation": "Explanation of risk level",
        "string_changes": "String changes made/needed?",
        "is_android_affected": "Is Android affected?",
    }

    # User who submitted the form.
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)

    user_impact = models.TextField(blank=False)

    covered_by_testing = models.CharField(
        blank=False,
        choices=YesNoUnknownChoices.choices,
        max_length=8,
        default=YesNoUnknownChoices.YES,
    )

    fix_verified_in_nightly = models.CharField(
        blank=False,
        choices=YesNoChoices.choices,
        max_length=3,
        default=YesNoChoices.YES,
    )

    needs_manual_qe_testing = models.CharField(
        blank=False,
        choices=YesNoChoices.choices,
        max_length=3,
        default=YesNoChoices.YES,
    )

    qe_testing_reproduction_steps = models.TextField(blank=True)

    risk_associated_with_patch = models.CharField(
        blank=False,
        choices=LowMediumHighChoices.choices,
        max_length=6,
        default=LowMediumHighChoices.LOW,
    )

    risk_level_explanation = models.TextField(blank=False)

    string_changes = models.TextField(blank=False)

    is_android_affected = models.CharField(
        blank=False,
        choices=YesNoUnknownChoices.choices,
        max_length=8,
        default=YesNoUnknownChoices.YES,
    )

    def to_conduit_json(self) -> dict[str, Any]:
        """Return the assessment in Conduit API JSON format."""
        return {
            label: getattr(self, name) for name, label in self.CONDUIT_FIELDS.items()
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

    @classmethod
    def link_revision_to_assessment(
        cls, revision_id: int, assessment: UpliftAssessment
    ) -> tuple["UpliftRevision", bool]:
        """Link a revision to an assessment, creating or updating the record.

        Returns a tuple of the `UpliftRevision` instance and a boolean
        indicating whether a new record was created (`True`) or an
        existing one was updated (`False`).
        """
        return cls.objects.update_or_create(
            revision_id=revision_id,
            defaults={"assessment": assessment},
        )


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

    # Phabricator uplift revision IDs as an ordered list of integers.
    # Example: If D1->D2->D3 is requested for uplift to beta, which
    # creates revisions D4->D5->D6, this field will be set to
    # `[4, 5, 6]`.
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

    # Unsorted references to the `Revision` objects the job will use
    # to apply the uplift request to the target.
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
