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
from lando.ui.uplift.context import UpliftContext, UpliftTrainRow
from lando.utils.phabricator import PhabricatorRevisionStatus


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
        revision_repo=None,
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
        revision_repo=None,
    )

    assert context.request_form.initial["source_revisions"] == [
        100,
        200,
        300,
    ], "Should have walked from root A through B to C."


@pytest.mark.django_db
def test_card_carries_every_job_queued_from_its_assessment(
    user, repo_mc, django_assert_num_queries
):
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

    # Assessments, revision links, submissions, and jobs are fetched in bulk.
    with django_assert_num_queries(4):
        cards = UpliftContext.build_assessment_cards(
            bug_id, 100, None, is_uplift_revision=True
        )
    jobs_by_assessment = {card.assessment.pk: list(card.jobs) for card in cards}

    assert jobs_by_assessment[assessment.pk] == jobs, (
        "Both submissions' jobs should appear on the assessment's card."
    )
    assert jobs_by_assessment[other_assessment.pk] == [other_job], (
        "A card should only carry the jobs queued from its own assessment."
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

    (card,) = UpliftContext.build_assessment_cards(
        bug_id, 100, None, is_uplift_revision=True
    )

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

    cards = UpliftContext.build_assessment_cards(
        bug_id, 100, None, is_uplift_revision=True
    )

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
        for card in UpliftContext.build_assessment_cards(
            bug_id, revision_id, linked, is_uplift_revision=True
        )
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
def test_mainline_revision_shows_only_the_uplifts_requested_from_it(user):
    """A mainline revision is not an uplift, so only its own uplift requests show.

    Other assessments on the bug belong to uplift revisions and would only
    invite writing or linking an assessment where none applies.
    """
    bug_id = 808080
    revision_id = 100

    requested = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftSubmission.objects.create(
        requested_by=user, assessment=requested, requested_revision_ids=[revision_id]
    )
    UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )

    mainline_cards = UpliftContext.build_assessment_cards(
        bug_id, revision_id, None, is_uplift_revision=False
    )
    uplift_cards = UpliftContext.build_assessment_cards(
        bug_id, revision_id, None, is_uplift_revision=True
    )

    assert [card.assessment for card in mainline_cards] == [requested], (
        "A mainline revision should only show the uplift requested from it."
    )
    assert len(uplift_cards) == 2, (
        "An uplift revision should show every assessment on the bug."
    )


@pytest.mark.django_db
def test_authoring_an_assessment_needs_an_uplift_revision_a_bug_and_a_login(user):
    """The assessment forms are offered only to a logged-in user on an uplift.

    A mainline revision is not an uplift, so its assessments come from
    "Request Uplift" instead.
    """
    authenticated = MagicMock()
    authenticated.user.is_authenticated = True

    anonymous = MagicMock()
    anonymous.user.is_authenticated = False

    assert UpliftContext.can_author_assessment(authenticated, 123, True), (
        "A logged-in user on an uplift revision with a bug should get the forms."
    )
    assert not UpliftContext.can_author_assessment(authenticated, 123, False), (
        "A mainline revision should not offer the assessment forms."
    )
    assert not UpliftContext.can_author_assessment(authenticated, None, True), (
        "A revision with no bug has nothing to file an assessment against."
    )
    assert not UpliftContext.can_author_assessment(anonymous, 123, True), (
        "An anonymous user should not get the forms."
    )


@pytest.mark.django_db
def test_train_rows_describe_each_stack_by_train(user, repo_mc, phabdouble):
    """A card has a row per job, then a row per stack linked from outside Lando.

    Lando only records which assessment a hand-linked stack carries, so its
    train and status come from Phabricator.
    """
    bug_id = 909090
    beta = repo_mc(scm_type=SCMType.GIT, name="firefox-beta", approval_required=True)
    release = repo_mc(
        scm_type=SCMType.GIT, name="firefox-release", approval_required=True
    )
    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user, assessment=assessment, requested_revision_ids=[100]
    )
    job = UpliftJob.objects.create(
        submission=submission,
        requester_email=user.email,
        status=JobStatus.LANDED,
        target_repo=beta,
        created_revision_ids=[301, 302],
    )
    UpliftRevision.link_revision_to_assessment(302, assessment)

    outside = phabdouble.revision(
        repo=phabdouble.repo(name=release.short_name),
        status=PhabricatorRevisionStatus.NEEDS_REVIEW,
        bug_id=bug_id,
    )
    UpliftRevision.link_revision_to_assessment(outside["id"], assessment)

    (card,) = UpliftContext.build_assessment_cards(
        bug_id,
        outside["id"],
        assessment,
        is_uplift_revision=True,
        phab=phabdouble.get_phabricator_client(),
    )

    assert card.train_rows == [
        UpliftTrainRow(train=beta.name, tip_revision_id=302, job=job),
        UpliftTrainRow(
            train=release.name,
            tip_revision_id=outside["id"],
            status_value="needs-review",
            status_name="Needs Review",
        ),
    ], "Each stack should be listed under its train, with the job's tip first."


@pytest.mark.django_db
def test_train_rows_leave_the_train_unknown_without_phabricator(user):
    """A hand-linked stack Phabricator cannot describe keeps an unknown train."""
    bug_id = 919191
    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(555, assessment)

    (card,) = UpliftContext.build_assessment_cards(
        bug_id, 555, assessment, is_uplift_revision=True
    )

    assert card.train_rows == [UpliftTrainRow(train=None, tip_revision_id=555)], (
        "Without a Phabricator lookup the stack should still be listed."
    )


@pytest.mark.django_db
def test_train_lookup_failure_does_not_break_the_page(user, phabdouble):
    """A revision Phabricator does not return leaves its train unknown."""
    bug_id = 929292
    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
    )
    UpliftRevision.link_revision_to_assessment(99999, assessment)

    (card,) = UpliftContext.build_assessment_cards(
        bug_id,
        99999,
        assessment,
        is_uplift_revision=True,
        phab=phabdouble.get_phabricator_client(),
    )

    assert card.train_rows == [UpliftTrainRow(train=None, tip_revision_id=99999)], (
        "A failed lookup should fall back to an unknown train."
    )
