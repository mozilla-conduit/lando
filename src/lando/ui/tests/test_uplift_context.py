from unittest.mock import MagicMock

import pytest

from lando.api.legacy.stacks import RevisionStack
from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftSubmission,
)
from lando.main.scm import SCMType
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


@pytest.mark.django_db
def test_assessments_for_bug_is_empty_without_a_bug(user):
    """A revision with no bug number groups with nothing.

    Without the guard, filtering on a `None` bug would match every assessment
    that predates the field.
    """
    UpliftAssessment.objects.create(user=user, bug_id=555, **UPLIFT_ASSESSMENT_ANSWERS)
    UpliftAssessment.objects.create(user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS)

    assert not UpliftAssessment.for_bug(None).exists(), (
        "`for_bug` should return nothing when the bug is unknown."
    )


@pytest.mark.django_db
def test_card_carries_every_job_queued_from_its_assessment(user, repo_mc):
    """A submission is an assessment plus jobs, so all its jobs sit on one card.

    Requesting an uplift twice against the same assessment creates two
    submissions; both sets of jobs belong on that assessment's card.
    """
    bug_id = 424242
    beta = repo_mc(scm_type=SCMType.GIT, name="firefox-beta", approval_required=True)
    release = repo_mc(
        scm_type=SCMType.GIT, name="firefox-release", approval_required=True
    )

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )

    jobs = []
    for repo in (beta, release):
        submission = UpliftSubmission.objects.create(
            requested_by=user, assessment=assessment, requested_revision_ids=[100]
        )
        jobs.append(
            UpliftJob.objects.create(
                submission=submission,
                requester_email=user.email,
                status=JobStatus.SUBMITTED,
                target_repo=repo,
            )
        )

    # An unrelated assessment's job must not leak onto the card.
    other_assessment = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    other_submission = UpliftSubmission.objects.create(
        requested_by=user, assessment=other_assessment, requested_revision_ids=[100]
    )
    other_job = UpliftJob.objects.create(
        submission=other_submission,
        requester_email=user.email,
        status=JobStatus.SUBMITTED,
        target_repo=beta,
    )

    cards = UpliftContext.build_assessment_cards(bug_id, None)
    jobs_by_assessment = {card.assessment.pk: list(card.jobs) for card in cards}

    assert jobs_by_assessment[assessment.pk] == jobs, (
        "Both submissions' jobs should appear on the assessment's card."
    )
    assert jobs_by_assessment[other_assessment.pk] == [other_job], (
        "A card should only carry the jobs queued from its own assessment."
    )
