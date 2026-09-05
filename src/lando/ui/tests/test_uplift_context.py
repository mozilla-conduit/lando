from unittest.mock import MagicMock

import pytest

from lando.api.legacy.stacks import RevisionStack
from lando.main.models.uplift import UpliftAssessment
from lando.ui.uplift.context import UpliftContext


@pytest.mark.django_db
def test_uplift_context_build_falls_back_on_stack_walk_error():
    """Test that UpliftContext.build() falls back to single revision on stack walk error.

    When iter_stack_from_root raises a ValueError (e.g., disconnected graph components),
    the build method should fall back to using just the current revision ID instead of
    crashing.
    """
    mock_stack = MagicMock(spec=RevisionStack)
    mock_stack.iter_stack_from_root.side_effect = ValueError(
        "Could not walk from a root node to PHID-REV-xyz."
    )

    mock_request = MagicMock()
    mock_request.user.is_authenticated = False

    revision_id = 123
    revision_phid = "PHID-REV-xyz"

    revisions = {
        revision_phid: {"id": f"D{revision_id}"},
    }

    context = UpliftContext.build(
        request=mock_request,
        revision_repo=None,
        revision_id=revision_id,
        revision_phid=revision_phid,
        revisions=revisions,
        stack=mock_stack,
    )

    assert context.request_form.initial["source_revisions"] == [revision_id], (
        "Form should be initialized with current revision."
    )


@pytest.mark.django_db
def test_uplift_context_build_walks_stack_successfully():
    """Test that UpliftContext.build() correctly walks the stack when possible."""
    # Create a simple linear stack: A -> B -> C (using PHIDs as node names).
    nodes = {"PHID-REV-a", "PHID-REV-b", "PHID-REV-c"}
    edges = {("PHID-REV-b", "PHID-REV-a"), ("PHID-REV-c", "PHID-REV-b")}
    stack = RevisionStack(nodes, edges)

    mock_request = MagicMock()
    mock_request.user.is_authenticated = False

    # We want to walk to node C. Revision IDs must be strings like "D123".
    revisions = {
        "PHID-REV-a": {"id": "D100"},
        "PHID-REV-b": {"id": "D200"},
        "PHID-REV-c": {"id": "D300"},
    }

    context = UpliftContext.build(
        request=mock_request,
        revision_repo=None,
        revision_id=300,
        revision_phid="PHID-REV-c",
        revisions=revisions,
        stack=stack,
    )

    assert context.request_form.initial["source_revisions"] == [
        100,
        200,
        300,
    ], "Should have walked from root A through B to C."


ASSESSMENT_FIELDS = {
    "user_impact": "Impact.",
    "covered_by_testing": "yes",
    "fix_verified_in_nightly": "no",
    "needs_manual_qe_testing": "no",
    "qe_testing_reproduction_steps": "",
    "risk_associated_with_patch": "low",
    "risk_level_explanation": "Low risk.",
    "string_changes": "None.",
    "is_android_affected": "no",
}


@pytest.mark.django_db
def test_assessments_for_bug_includes_other_users(user, django_user_model):
    """Assessments for a bug are returned regardless of who authored them."""
    other_user = django_user_model.objects.create_user(
        username="other", email="other@example.com"
    )

    mine = UpliftAssessment.objects.create(user=user, bug_id=555, **ASSESSMENT_FIELDS)
    theirs = UpliftAssessment.objects.create(
        user=other_user, bug_id=555, **ASSESSMENT_FIELDS
    )
    UpliftAssessment.objects.create(user=user, bug_id=666, **ASSESSMENT_FIELDS)

    assert list(UpliftAssessment.for_bug(555)) == [mine, theirs], (
        "Both users' assessments for the bug should be returned, oldest first."
    )


@pytest.mark.django_db
def test_assessments_for_bug_is_empty_without_a_bug(user):
    """A revision with no bug number groups with nothing."""
    UpliftAssessment.objects.create(user=user, bug_id=555, **ASSESSMENT_FIELDS)

    assert not UpliftAssessment.for_bug(None).exists(), (
        "`for_bug` should return nothing when the bug is unknown."
    )


@pytest.mark.django_db
def test_uplift_context_exposes_the_bug_and_its_assessments(user):
    """The context carries the revision's bug and every assessment against it."""
    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=777, **ASSESSMENT_FIELDS
    )

    stack = RevisionStack({"PHID-REV-a"}, set())

    mock_request = MagicMock()
    mock_request.user.is_authenticated = False

    context = UpliftContext.build(
        request=mock_request,
        revision_repo=None,
        revision_id=100,
        revision_phid="PHID-REV-a",
        revisions={"PHID-REV-a": {"id": "D100", "bug_id": 777}},
        stack=stack,
    )

    assert context.bug_id == 777, "The revision's bug number should be exposed."
    assert [card.assessment for card in context.bug_assessments] == [assessment], (
        "The bug's existing assessment should be offered for linking."
    )
    assert not context.bug_assessments[0].is_linked, (
        "An assessment not linked to this revision should not be marked as linked."
    )
