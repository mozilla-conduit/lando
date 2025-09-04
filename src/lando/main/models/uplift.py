import json
from typing import Any, Self

from django.contrib.auth.models import User
from django.db import models
from django.forms.models import model_to_dict

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


class UpliftAssessment(BaseModel):
    """Represents the responses to the uplift request form."""

    # User who submitted the form.
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING)

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

    @classmethod
    def from_cleaned_form(cls, user: User, cleaned_data: dict[str, str]) -> Self:
        """Create an `UpliftAssessment` from cleaned form data."""
        return cls.objects.create(
            user=user,
            user_impact=cleaned_data["user_impact"],
            covered_by_testing=cleaned_data["covered_by_testing"],
            fix_verified_in_nightly=cleaned_data["fix_verified_in_nightly"],
            needs_manual_qe_testing=cleaned_data["needs_manual_qe_testing"],
            qe_testing_reproduction_steps=cleaned_data["qe_testing_reproduction_steps"],
            risk_associated_with_patch=cleaned_data["risk_associated_with_patch"],
            risk_level_explanation=cleaned_data["risk_level_explanation"],
            string_changes=cleaned_data["string_changes"],
            is_android_affected=cleaned_data["is_android_affected"],
        )

    def to_form_dict(self) -> dict[str, Any]:
        """Return the assessment as a dict for the `initial` form argument."""
        return model_to_dict(self, exclude=["id"])

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
