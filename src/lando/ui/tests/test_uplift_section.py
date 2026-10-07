from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.template import engines
from django.urls import reverse

from lando.api.legacy.stacks import RevisionStack
from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models.uplift import UpliftAssessment
from lando.ui.uplift.context import UpliftContext

REVISION_PHID = "PHID-REV-uplift"


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
        revisions={REVISION_PHID: {"id": f"D{revision_id}", "bug_id": bug_id}},
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
