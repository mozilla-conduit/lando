from django.contrib.auth.models import User
from django.db import models

from lando.main.models import BaseModel


class UpliftRequestForm(BaseModel):
    """Represents the responses to the uplift request form."""

    # User who submitted the form.
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # User impact if declined?
    user_impact = models.TextField(blank=False)

    # Code covered by automated testing?
    covered_by_testing = models.BooleanField(blank=False)

    # Fix verified in Nightly.
    fix_verified_in_nightly = models.BooleanField(blank=False)

    # Needs manual QE test.
    needs_manual_qe_testing = models.BooleanField(blank=False)

    # Steps to reproduce for manual QE testing.
    qe_testing_reproduction_steps = models.TextField(blank=True)

    # Risk associated with taking this patch.
    risk_associated_with_patch = models.TextField(blank=False)

    # Explanation of risk level.
    risk_level_explanation = models.TextField(blank=False)

    # String changes made/needed?
    string_changes = models.TextField(blank=False)

    # Is Android affected?
    is_android_affected = models.BooleanField(blank=False)


class UpliftRevision(BaseModel):
    """Link an uplift request form to a revision."""

    uplift_request = models.ForeignKey(
        UpliftRequestForm, on_delete=models.CASCADE, related_name="revisions"
    )

    # Phabricator revision ID, ie `1234` for `D1234`.
    revision_id = models.IntegerField(blank=True, null=True, unique=True)

    class Meta:
        unique_together = ("uplift_request", "revision_id")
