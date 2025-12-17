import pytest
from django.contrib.auth.models import User

from lando.ui.legacy.forms import UpliftAssessmentLinkForm, UserSettingsForm


@pytest.mark.parametrize(
    "phabricator_api_key,is_valid",
    [
        ("", True),
        ("api-123456789012345678901234567x", True),
        ("api-123", False),
        ("xxx", False),
        ("xxx-123456789012345678901234567x", False),
        ("api-123456789012345678901234567X", False),
    ],
)
def test_user_settings(phabricator_api_key, is_valid):
    form = UserSettingsForm({"phabricator_api_key": phabricator_api_key})
    assert form.is_valid() == is_valid


@pytest.mark.parametrize(
    "revision_ids_input,expected_output,should_be_valid",
    [
        # Valid cases
        ("1234", [1234], True),
        ("1234,5678", [1234, 5678], True),
        ("1234, 5678, 9012", [1234, 5678, 9012], True),
        ("  1234  ,  5678  ", [1234, 5678], True),
        ("1234,5678,9012,3456", [1234, 5678, 9012, 3456], True),
        # Invalid cases
        ("", None, False),
        ("   ", None, False),
        ("abc", None, False),
        ("1234,abc", None, False),
        ("1234,", [1234], True),  # Trailing comma is OK, gets filtered out
        (",1234", [1234], True),  # Leading comma is OK, gets filtered out
        (
            "1234,,5678",
            [1234, 5678],
            True,
        ),  # Double comma is OK, empty strings filtered
    ],
)
def test_uplift_assessment_link_form_revision_ids(
    revision_ids_input, expected_output, should_be_valid, db
):
    """Test the revision_ids field validation in UpliftAssessmentLinkForm."""
    # Create a test user for the form
    user = User.objects.create_user(username="testuser", email="test@example.com")

    # Minimal valid form data with required uplift assessment fields
    form_data = {
        "revision_ids": revision_ids_input,
        "user_impact": "Test impact",
        "covered_by_testing": "yes",
        "fix_verified_in_nightly": "yes",
        "needs_manual_qe_testing": "no",
        "qe_testing_reproduction_steps": "",
        "risk_associated_with_patch": "low",
        "risk_level_explanation": "Test explanation",
        "string_changes": "None",
        "is_android_affected": "no",
    }

    form = UpliftAssessmentLinkForm(form_data, user=user)

    if should_be_valid:
        assert form.is_valid(), f"Form should be valid but has errors: {form.errors}"
        assert form.cleaned_data["revision_ids"] == expected_output
    else:
        assert not form.is_valid()
        assert "revision_ids" in form.errors
