from django.contrib.auth.models import User
from django.db import models

from lando.main.models import BaseModel

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


class UpliftQuestionnaireResponse(BaseModel):
    """Represents the responses to the uplift request form."""

    # User who submitted the form.
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # User impact if declined?
    user_impact = models.TextField(blank=False)

    # Code covered by automated testing?
    covered_by_testing = models.CharField(
        blank=False, choices=YesNoUnknownChoices.choices, max_length=8
    )

    # Fix verified in Nightly.
    fix_verified_in_nightly = models.CharField(
        blank=False, choices=YesNoChoices.choices, max_length=3
    )

    # Needs manual QE test.
    needs_manual_qe_testing = models.CharField(
        blank=False, choices=YesNoChoices.choices, max_length=3
    )

    # Steps to reproduce for manual QE testing.
    qe_testing_reproduction_steps = models.TextField(blank=True)

    # Risk associated with taking this patch.
    risk_associated_with_patch = models.CharField(
        blank=False, choices=LowMediumHighChoices.choices, max_length=6
    )

    # Explanation of risk level.
    risk_level_explanation = models.TextField(blank=False)

    # String changes made/needed?
    string_changes = models.TextField(blank=False)

    # Is Android affected?
    is_android_affected = models.CharField(
        blank=False, choices=YesNoUnknownChoices.choices, max_length=8
    )


class UpliftRevision(BaseModel):
    """Link an uplift request form to a revision."""

    questionnaire_response = models.ForeignKey(
        UpliftQuestionnaireResponse, on_delete=models.CASCADE, related_name="revisions"
    )

    # Phabricator revision ID, ie `1234` for `D1234`.
    revision_id = models.IntegerField(blank=True, null=True, unique=True)

    class Meta:
        unique_together = ("questionnaire_response", "revision_id")
