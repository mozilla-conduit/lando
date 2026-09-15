from unittest.mock import MagicMock

import pytest

from lando.api.legacy.stacks import RevisionStack
from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
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

    cards = UpliftContext.build_assessment_cards(bug_id, 100, None)
    jobs_by_assessment = {card.assessment.pk: list(card.jobs) for card in cards}

    assert jobs_by_assessment[assessment.pk] == jobs, (
        "Both submissions' jobs should appear on the assessment's card."
    )
    assert jobs_by_assessment[other_assessment.pk] == [other_job], (
        "A card should only carry the jobs queued from its own assessment."
    )


@pytest.mark.django_db
def test_assessment_with_no_bug_still_shows_on_its_revisions(user, repo_mc):
    """Assessments predating `bug_id` stay visible without a backfill.

    They have no bug to group by, so the revisions they reach are the only
    thing keeping them on the page.
    """
    linked_revision_id = 100
    requested_revision_id = 200
    created_revision_id = 300
    repo = repo_mc(scm_type=SCMType.GIT, name="firefox-beta", approval_required=True)

    linked = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(linked_revision_id, linked)

    requested = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user,
        assessment=requested,
        requested_revision_ids=[requested_revision_id],
    )
    UpliftJob.objects.create(
        submission=submission,
        requester_email=user.email,
        status=JobStatus.SUBMITTED,
        target_repo=repo,
        created_revision_ids=[created_revision_id],
    )

    unrelated = UpliftAssessment.objects.create(
        user=user, bug_id=None, **UPLIFT_ASSESSMENT_ANSWERS
    )

    for revision_id, expected in (
        (linked_revision_id, linked),
        (requested_revision_id, requested),
        (created_revision_id, requested),
    ):
        visible = list(UpliftAssessment.visible_on_revision(None, revision_id))
        assert visible == [expected], (
            f"D{revision_id} should reach assessment {expected.pk} with no bug set."
        )
        assert unrelated not in visible, (
            "An assessment the revision does not reach should stay hidden."
        )


@pytest.mark.django_db
def test_card_lists_the_revisions_an_uplift_was_requested_for(user, repo_mc):
    """Requesting an uplift records no revision link, so the card reads submissions.

    `UpliftRequestView` only stores `requested_revision_ids`, so without this
    the card would claim the assessment reaches no revisions at all.
    """
    bug_id = 515151
    repo = repo_mc(scm_type=SCMType.GIT, name="firefox-beta", approval_required=True)

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user,
        assessment=assessment,
        requested_revision_ids=[100, 200],
    )
    UpliftJob.objects.create(
        submission=submission,
        requester_email=user.email,
        status=JobStatus.SUBMITTED,
        target_repo=repo,
    )

    (card,) = UpliftContext.build_assessment_cards(bug_id, 100, None)

    assert card.requested_revision_ids == [100, 200], (
        "The card should list the revisions the uplift was requested for."
    )
    assert card.revision_ids == [], (
        "Requesting an uplift does not make a revision carry the form."
    )


@pytest.mark.django_db
def test_cards_include_assessments_authored_by_other_users(user, django_user_model):
    """A bug's assessments are shown whoever wrote them."""
    bug_id = 606060
    other_user = django_user_model.objects.create_user(
        username="colleague", email="colleague@example.com"
    )

    mine = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    theirs = UpliftAssessment.objects.create(
        user=other_user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )

    cards = UpliftContext.build_assessment_cards(bug_id, 100, None)

    assert [card.assessment for card in cards] == [mine, theirs], (
        "Both users' assessments should be shown, oldest first."
    )


@pytest.mark.django_db
def test_only_the_linked_assessments_card_is_marked_linked(user):
    """Just the assessment attached to the revision is flagged as linked."""
    bug_id = 707070
    revision_id = 100

    linked = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(revision_id, linked)

    other = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )

    cards = {
        card.assessment.pk: card
        for card in UpliftContext.build_assessment_cards(bug_id, revision_id, linked)
    }

    assert cards[linked.pk].is_linked, (
        "The assessment attached to the revision should be marked as linked."
    )
    assert cards[linked.pk].revision_ids == [revision_id], (
        "The linked card should list the revision carrying its form."
    )
    assert not cards[other.pk].is_linked, (
        "An assessment not attached to the revision should not be marked as linked."
    )


@pytest.mark.django_db
def test_authoring_an_assessment_needs_a_bug_and_a_login(user):
    """The assessment forms are offered only to a logged-in user on a bug.

    Notably not gated on the repo being an uplift target, which would hide the
    forms from the revision an uplift is requested from.
    """
    authenticated = MagicMock()
    authenticated.user.is_authenticated = True

    anonymous = MagicMock()
    anonymous.user.is_authenticated = False

    assert UpliftContext.can_author_assessment(authenticated, 123), (
        "A logged-in user on a revision with a bug should get the forms."
    )
    assert not UpliftContext.can_author_assessment(authenticated, None), (
        "A revision with no bug has nothing to file an assessment against."
    )
    assert not UpliftContext.can_author_assessment(anonymous, 123), (
        "An anonymous user should not get the forms."
    )
