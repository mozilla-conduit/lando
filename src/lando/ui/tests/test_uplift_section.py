from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.template import engines
from django.urls import reverse

from lando.api.legacy.stacks import RevisionStack
from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models.uplift import UpliftAssessment, UpliftRevision
from lando.ui.uplift.context import UpliftContext

REVISION_PHID = "PHID-REV-uplift"
REVISION_URL = "https://phabricator.test/D4219"


class ElementCollector(HTMLParser):
    """Collect every start tag and its attributes from rendered markup."""

    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.elements.append((tag, dict(attrs)))


def elements(html: str, tag: str, **attributes: str) -> list[dict]:
    """Return the attributes of every `tag` element carrying `attributes`."""
    collector = ElementCollector()
    collector.feed(html)
    return [
        attrs
        for element_tag, attrs in collector.elements
        if element_tag == tag
        and all(attrs.get(name) == value for name, value in attributes.items())
    ]


def render_uplift_section(
    rf, user, revision_id: int, bug_id: int | None, *, uplift_repo: bool = True
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
            }
        },
        stack=RevisionStack({REVISION_PHID}, set()),
        revision_repo=revision_repo,
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
    assert "Before release managers can approve D4219" in html, (
        "The checklist should lead the uplift section."
    )
