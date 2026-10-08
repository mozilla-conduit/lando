from types import SimpleNamespace

import pytest
from django.template import engines
from django.urls import reverse

from lando.api.legacy.stacks import RevisionStack
from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftRevision,
    UpliftSubmission,
)
from lando.ui.tests.markup import elements, squashed
from lando.ui.uplift.context import UpliftContext

REVISION_PHID = "PHID-REV-uplift"
REVISION_URL = "https://phabricator.test/D4219"


def render_uplift_section(
    rf,
    user,
    revision_id: int,
    bug_id: int | None,
    *,
    uplift_repo: bool = True,
    phab=None,
    reviewers: list[dict] | None = None,
) -> str:
    """Render the revision page's uplift section as `user` would see it."""
    request = rf.get(f"/D{revision_id}/")
    request.user = user
    revision_repo = SimpleNamespace(approval_required=uplift_repo)

    uplift = UpliftContext.build(
        request=request,
        revision_id=revision_id,
        revision_phid=REVISION_PHID,
        revisions={
            REVISION_PHID: {
                "id": f"D{revision_id}",
                "bug_id": bug_id,
                "url": REVISION_URL,
                "reviewers": reviewers or [],
            }
        },
        stack=RevisionStack({REVISION_PHID}, set()),
        revision_repo=revision_repo,
        phab=phab,
    )

    template = engines["jinja2"].get_template("stack/partials/uplift-section.html")
    return template.render(
        {
            "uplift": uplift,
            "revision_repo": revision_repo,
            "user_has_phabricator_token": True,
        },
        request,
    )


@pytest.mark.django_db
def test_unlinked_uplift_revision_asks_for_its_assessment_once(rf, user):
    """An unlinked uplift revision picks its assessment from one radio group.

    Linking an existing assessment and creating a new one are answers to the
    same question, so they share one form instead of a button per assessment.
    """
    bug_id = 1601002
    revision_id = 4219
    first, second = (
        UpliftAssessment.objects.create(
            user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
        )
        for assessment_number in range(2)
    )

    html = render_uplift_section(rf, user, revision_id, bug_id)

    pickers = elements(html, "form", **{"class": "AssessmentPicker-form"})
    assert len(pickers) == 1, "The revision should ask for its assessment once."
    assert pickers[0]["action"] == reverse(
        "uplift-assessment-link-page", args=[revision_id]
    ), "The picker should post to the link endpoint."

    choices = [
        radio["value"]
        for radio in elements(html, "input", type="radio", name="assessment")
    ]
    assert choices == [str(first.id), str(second.id), "new"], (
        "Each assessment should be a choice, followed by `None of these`."
    )
    assert "Link assessment #" not in html, (
        "There should be no per-assessment link buttons alongside the picker."
    )
    assert "Create new assessment for bug" not in html, (
        "Creating should be the picker's `None of these` answer, not a button."
    )
    assert "hidden" not in elements(html, "li", id="uplift-assessment-picker")[0], (
        "With nothing linked, choosing an assessment is the open task."
    )
    assert len(elements(html, "p", **{"class": "AssessmentPicker-facts"})) == 2, (
        "Each assessment's distinguishing answers should share one line."
    )


def create_assessments(user, bug_id: int, count: int) -> list[UpliftAssessment]:
    """Create `count` assessments filed against `bug_id`."""
    return [
        UpliftAssessment.objects.create(
            user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_ANSWERS
        )
        for assessment_number in range(count)
    ]


@pytest.mark.django_db
def test_linked_uplift_revision_changes_its_assessment_behind_one_button(rf, user):
    """A linked revision shows its assessment, with the picker behind `Change`."""
    bug_id = 1601002
    revision_id = 4218
    linked, other = create_assessments(user, bug_id, 2)
    UpliftRevision.link_revision_to_assessment(revision_id, linked)

    html = render_uplift_section(rf, user, revision_id, bug_id)

    toggles = elements(
        html, "button", **{"class": "button is-small UpliftReadiness-toggle"}
    )
    assert len(toggles) == 1, "The assessment item should have one `Change` button."
    assert "hidden" in elements(html, "li", id="uplift-assessment-picker")[0], (
        "The picker should stay closed until the user asks to change."
    )
    checked = [
        radio["value"]
        for radio in elements(html, "input", type="radio", name="assessment")
        if "checked" in radio
    ]
    assert checked == [str(linked.id)], (
        "The picker should start on the assessment already linked."
    )
    assert "Link assessment #" not in html, (
        "Other assessments should not carry their own link buttons."
    )
    assert "Create new assessment for bug" not in html, (
        "Creating should be reached through `Change`, not a separate button."
    )


@pytest.mark.django_db
def test_uplift_revision_without_assessments_offers_to_create_one(rf, user):
    """With no assessment on the bug, the checklist item creates the first one."""
    html = render_uplift_section(rf, user, 4224, 1601004)

    assert not elements(html, "form", **{"class": "AssessmentPicker-form"}), (
        "There is nothing to pick from, so there should be no picker."
    )
    assert elements(
        html,
        "button",
        **{
            "class": "button is-small is-primary assessment-modal-open",
            "data-assessment-modal": "new",
        },
    ), "The assessment item should open the new-assessment modal."


@pytest.mark.django_db
def test_uplift_revision_without_a_bug_points_to_phabricator(rf, user):
    """A missing bug number is the first fix, and is made in Phabricator."""
    html = render_uplift_section(rf, user, 4225, None)

    links = elements(html, "a", href=REVISION_URL)
    assert links, "The bug number item should link to the revision in Phabricator."
    assert "Needs a bug number first." in html, (
        "The assessment item should wait on the bug number."
    )
    assert "Uplift assessments for" not in html, (
        "Without a bug there are no assessments to list."
    )


@pytest.mark.django_db
@pytest.mark.parametrize("linked", [True, False])
def test_uplift_revision_no_longer_warns_off_request_uplift(rf, user, linked):
    """The checklist replaces the warning that the revision needs no new uplift."""
    bug_id = 1601002
    revision_id = 4219
    (assessment,) = create_assessments(user, bug_id, 1)
    if linked:
        UpliftRevision.link_revision_to_assessment(revision_id, assessment)

    html = render_uplift_section(rf, user, revision_id, bug_id)

    assert "does not need" not in html, (
        "The `Request Uplift` warning should be gone from the uplift section."
    )
    assert 'class="box UpliftReadiness' in html, (
        "The checklist should lead the uplift section."
    )


@pytest.mark.django_db
def test_linked_uplift_revision_shows_only_its_own_assessment_in_full(rf, user):
    """The linked assessment gets the card; the bug's others fold under it."""
    bug_id = 1601002
    revision_id = 4218
    linked, other = create_assessments(user, bug_id, 2)
    UpliftRevision.link_revision_to_assessment(revision_id, linked)
    UpliftRevision.link_revision_to_assessment(4221, linked)

    html = render_uplift_section(rf, user, revision_id, bug_id)

    assert len(elements(html, "div", **{"class": "box"})) == 1, (
        "Only the linked assessment should be shown as a full card."
    )
    assert "1 other assessment for bug 1601002" in squashed(html), (
        "The bug's other assessment should be folded under the linked one."
    )
    assert "Edits also apply to D4221." in squashed(html), (
        "Editing a shared assessment should say which revisions it changes."
    )


@pytest.mark.django_db
def test_unlinked_uplift_revision_shows_no_cards_beside_the_picker(rf, user):
    """The picker already lists every assessment, so no cards repeat them."""
    create_assessments(user, 1601002, 2)

    html = render_uplift_section(rf, user, 4219, 1601002)

    assert not elements(html, "div", **{"class": "box"}), (
        "An unlinked revision should not repeat the picker's assessments as cards."
    )
    assert "UpliftOthers" not in html, "There is no linked assessment to fold under."


@pytest.mark.django_db
def test_mainline_revision_shows_every_uplift_requested_from_it(rf, user):
    """A mainline revision has no checklist, and shows each requested uplift."""
    bug_id = 1601002
    revision_id = 4215
    (requested,) = create_assessments(user, bug_id, 1)
    UpliftSubmission.objects.create(
        requested_by=user, assessment=requested, requested_revision_ids=[revision_id]
    )

    html = render_uplift_section(rf, user, revision_id, bug_id, uplift_repo=False)

    assert "UpliftReadiness" not in html, (
        "A mainline revision is not approved for uplift, so it has no checklist."
    )
    assert len(elements(html, "div", **{"class": "box"})) == 1, (
        "The uplift requested from the revision should be shown as a card."
    )
    assert "Uplift assessments for" in html, "The cards should name their bug."


@pytest.mark.django_db
def test_linked_card_lists_its_stacks_by_train(rf, user):
    """The linked card names each stack by its tip, highlighting this revision's."""
    bug_id = 1601002
    revision_id = 4218
    (linked,) = create_assessments(user, bug_id, 1)
    UpliftRevision.link_revision_to_assessment(revision_id, linked)

    html = render_uplift_section(rf, user, revision_id, bug_id)

    assert "Stack tip" in html, "The table should name each stack by its tip."
    assert elements(html, "span", **{"class": "tag is-rounded is-primary"}), (
        "This revision's own stack tip should be highlighted."
    )
    assert "this page" not in html, "The highlight alone should mark this revision."
    assert "Linked revisions" not in html, (
        "The train table replaces the cluster of linked revision pills."
    )
    assert "Linked to this revision" not in html, (
        "The checklist already marks the linked assessment, so the card should not."
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "review,expected",
    [
        (None, "release-managers will be added as a reviewer on Phabricator."),
        ("blocking", "Waiting for release-managers to accept D4218 in Phabricator."),
        ("rejected", "release-managers requested changes to D4218 in Phabricator."),
        ("accepted", "Accepted by release-managers."),
    ],
)
def test_approval_item_reads_the_release_managers_review(
    rf, user, phabdouble, release_management_project, review, expected
):
    """The approval item agrees with the landing check on the group's review."""
    bug_id = 1601002
    revision_id = 4218
    (linked,) = create_assessments(user, bug_id, 1)
    UpliftRevision.link_revision_to_assessment(revision_id, linked)
    reviewers = (
        [{"phid": release_management_project["phid"], "status": review}]
        if review
        else []
    )

    html = render_uplift_section(
        rf,
        user,
        revision_id,
        bug_id,
        phab=phabdouble.get_phabricator_client(),
        reviewers=reviewers,
    )

    assert expected in squashed(html), (
        f"A `{review}` release-managers review should read `{expected}`."
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "revision_id,bug_id,linked,review,expected",
    [
        (4225, None, False, None, "D4225 needs a bug number"),
        (4219, 1601002, False, None, "D4219 needs an uplift assessment"),
        (
            4218,
            1601002,
            True,
            "rejected",
            "release-managers requested changes to D4218",
        ),
        (4218, 1601002, True, "blocking", "D4218 is ready for release manager review"),
        (4218, 1601002, True, "accepted", "D4218 is approved for uplift"),
    ],
)
def test_checklist_headline_names_the_state(
    rf,
    user,
    phabdouble,
    release_management_project,
    revision_id,
    bug_id,
    linked,
    review,
    expected,
):
    """The checklist's headline says what is left, or that nothing is."""
    if bug_id:
        (assessment,) = create_assessments(user, bug_id, 1)
        if linked:
            UpliftRevision.link_revision_to_assessment(revision_id, assessment)
    reviewers = (
        [{"phid": release_management_project["phid"], "status": review}]
        if review
        else []
    )

    html = render_uplift_section(
        rf,
        user,
        revision_id,
        bug_id,
        phab=phabdouble.get_phabricator_client(),
        reviewers=reviewers,
    )

    assert expected in squashed(html), f"The headline should read `{expected}`."
