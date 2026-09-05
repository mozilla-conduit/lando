import pytest

from lando.api.legacy.api.transplants import LegacyAPIException
from lando.main.models import Revision
from lando.main.models.uplift import UpliftAssessment, UpliftRevision
from lando.ui.legacy.stacks import (
    Edge,
    draw_stack_graph,
    sort_stack_topological,
)


def test_sort_stack_topological_single_node():
    order = sort_stack_topological({"PHID-DREV-0"}, set())
    assert len(order) == 1
    assert order[0] == "PHID-DREV-0"


def test_sort_stack_topological_linear():
    revs = ["PHID-DREV-{}".format(i) for i in range(10)]
    nodes = set(revs)
    edges = {Edge(child=revs[i], parent=revs[i - 1]) for i in range(1, 10)}

    order = sort_stack_topological(nodes, edges)
    assert order == revs


def test_sort_stack_topological_favors_minimum():
    nodes = set(range(10))
    edges = {Edge(child=0, parent=i) for i in range(1, 10)}

    order = sort_stack_topological(nodes, edges)
    assert order == list(range(1, 10)) + [0]


def test_sort_stack_topological_cycle():
    nodes = {1, 2, 3, 4}
    edges = {
        Edge(child=1, parent=2),
        Edge(child=2, parent=3),
        Edge(child=3, parent=1),
        Edge(child=1, parent=4),
    }

    with pytest.raises(ValueError):
        sort_stack_topological(nodes, edges)


def test_sort_stack_topological_complex():
    nodes = {"PHID-DREV-{}".format(i) for i in range(10)}
    edges = {
        Edge(child="PHID-DREV-1", parent="PHID-DREV-0"),
        Edge(child="PHID-DREV-2", parent="PHID-DREV-0"),
        Edge(child="PHID-DREV-2", parent="PHID-DREV-3"),
        Edge(child="PHID-DREV-4", parent="PHID-DREV-2"),
        Edge(child="PHID-DREV-5", parent="PHID-DREV-4"),
        Edge(child="PHID-DREV-6", parent="PHID-DREV-1"),
        Edge(child="PHID-DREV-7", parent="PHID-DREV-6"),
        Edge(child="PHID-DREV-7", parent="PHID-DREV-5"),
        Edge(child="PHID-DREV-9", parent="PHID-DREV-7"),
        Edge(child="PHID-DREV-8", parent="PHID-DREV-9"),
    }

    order = sort_stack_topological(nodes, edges, key=lambda x: int(x.split("-")[2]))
    assert order == [
        "PHID-DREV-0",
        "PHID-DREV-1",
        "PHID-DREV-3",
        "PHID-DREV-2",
        "PHID-DREV-4",
        "PHID-DREV-5",
        "PHID-DREV-6",
        "PHID-DREV-7",
        "PHID-DREV-9",
        "PHID-DREV-8",
    ]


def test_draw_stack_graph_complex():
    nodes = {"PHID-DREV-{}".format(i) for i in range(10)}
    edges = {
        Edge(child="PHID-DREV-1", parent="PHID-DREV-0"),
        Edge(child="PHID-DREV-2", parent="PHID-DREV-0"),
        Edge(child="PHID-DREV-2", parent="PHID-DREV-3"),
        Edge(child="PHID-DREV-4", parent="PHID-DREV-2"),
        Edge(child="PHID-DREV-5", parent="PHID-DREV-4"),
        Edge(child="PHID-DREV-6", parent="PHID-DREV-1"),
        Edge(child="PHID-DREV-7", parent="PHID-DREV-6"),
        Edge(child="PHID-DREV-7", parent="PHID-DREV-5"),
        Edge(child="PHID-DREV-9", parent="PHID-DREV-7"),
        Edge(child="PHID-DREV-8", parent="PHID-DREV-9"),
    }
    order = sort_stack_topological(nodes, edges, key=lambda x: int(x.split("-")[2]))

    width, rows = draw_stack_graph(nodes, edges, order)
    assert width == 3
    assert rows == [
        {"above": [0, 1], "below": [], "node": "PHID-DREV-0", "other": [], "pos": 0},
        {"above": [0], "below": [0], "node": "PHID-DREV-1", "other": [1], "pos": 0},
        {"above": [2], "below": [], "node": "PHID-DREV-3", "other": [0, 1], "pos": 2},
        {"above": [1], "below": [1, 2], "node": "PHID-DREV-2", "other": [0], "pos": 1},
        {"above": [1], "below": [1], "node": "PHID-DREV-4", "other": [0], "pos": 1},
        {"above": [1], "below": [1], "node": "PHID-DREV-5", "other": [0], "pos": 1},
        {"above": [0], "below": [0], "node": "PHID-DREV-6", "other": [1], "pos": 0},
        {"above": [0], "below": [0, 1], "node": "PHID-DREV-7", "other": [], "pos": 0},
        {"above": [0], "below": [0], "node": "PHID-DREV-9", "other": [], "pos": 0},
        {"above": [], "below": [0], "node": "PHID-DREV-8", "other": [], "pos": 0},
    ]


@pytest.mark.parametrize(
    "username,email,trigger",
    [
        ("Hackbot", "hackbot@mozilla.tld", True),
        ("Hackbot", " haCkbOt@moziLla.Tld ", True),
        ("Someone else", "test@example.org", False),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_transplant_disallowed_author_requires_author_override(
    username,
    email,
    trigger,
    user,
    authenticated_client,
    mocked_repo_config,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    scm_user,
):
    r1_author = phabdouble.user()
    d1_author = phabdouble.user(username=username, email=email)
    phabrepo = phabdouble.repo(name="mozilla-central")
    reviewer = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff(author=d1_author)
    r1 = phabdouble.revision(diff=d1, repo=phabrepo)
    phabdouble.reviewer(r1, reviewer)

    data = {"landing_path": '[{"revision_id": "D1", "diff_id": 1}]'}
    if trigger:
        revision_author = phabdouble.api_object_for(r1_author)
        context_data = authenticated_client.get(f"/D{r1['id']}/").context_data

        form = context_data["form"]
        assert (
            form.fields["author_name"].initial == revision_author["fields"]["realName"]
        )
        assert form.fields["author_email"].initial is None

        data["confirmation_token"] = context_data["dryrun"]["confirmation_token"]
        with pytest.raises(LegacyAPIException) as e:
            authenticated_client.post(f"/D{r1['id']}/", data=data)
        assert e.value.args == (
            400,
            "Mailbox values should be present if and only if disallowed authors are present.",
        )

        # Associate Lando user with the phabricator user and try again.
        user.profile.phabricator_phid = r1["authorPHID"]
        user.profile.save()
        form = authenticated_client.get(f"/D{r1['id']}/").context_data["form"]
        assert form.fields["author_name"].initial == user.profile.userinfo["name"]
        assert form.fields["author_email"].initial == user.profile.userinfo["email"]

        data["author_name"] = form.fields["author_name"].initial
        data["author_email"] = form.fields["author_email"].initial
        response = authenticated_client.post(f"/D{r1['id']}/", data=data)
        messages = list(response.wsgi_request._messages)
        revision = Revision.objects.get(revision_id=r1["id"], diff_id=d1["id"])
        assert len(messages) == 0

        assert revision.patch_data["author_name"] == data["author_name"]
        assert revision.patch_data["author_email"] == data["author_email"]
    else:
        form = authenticated_client.get(f"/D{r1['id']}/").context_data["form"]
        assert form.fields["author_name"].initial is None
        assert form.fields["author_email"].initial is None
        response = authenticated_client.post(f"/D{r1['id']}/", data=data)
        messages = list(response.wsgi_request._messages)
        assert len(messages) == 0

        revision = Revision.objects.get(revision_id=r1["id"], diff_id=d1["id"])
        assert revision.patch_data["author_name"] == d1["authorName"]
        assert revision.patch_data["author_email"] == d1["authorEmail"]


UPLIFT_ASSESSMENT_FIELDS = {
    "user_impact": "Crashes on startup for beta users.",
    "covered_by_testing": "yes",
    "fix_verified_in_nightly": "yes",
    "needs_manual_qe_testing": "no",
    "qe_testing_reproduction_steps": "",
    "risk_associated_with_patch": "low",
    "risk_level_explanation": "One-line null check.",
    "string_changes": "None.",
    "is_android_affected": "no",
}


@pytest.mark.django_db(transaction=True)
def test_stack_page_renders_the_bugs_uplift_assessment_cards(
    user,
    authenticated_client,
    mocked_repo_config,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    scm_user,
    django_user_model,
):
    """The revision page shows a card per assessment on the bug, whoever wrote it."""
    bug_id = 1234567
    phabrepo = phabdouble.repo(name="mozilla-uplift")
    revision = phabdouble.revision(repo=phabrepo, bug_id=bug_id)
    other_revision = phabdouble.revision(repo=phabrepo, bug_id=bug_id)

    other_user = django_user_model.objects.create_user(
        username="colleague", email="colleague@example.com"
    )

    # One assessment linked to this revision, one authored by a colleague and
    # linked elsewhere in the bug, and one against an unrelated bug.
    linked = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id, **UPLIFT_ASSESSMENT_FIELDS
    )
    UpliftRevision.link_revision_to_assessment(revision["id"], linked)

    colleagues = UpliftAssessment.objects.create(
        user=other_user, bug_id=bug_id, **UPLIFT_ASSESSMENT_FIELDS
    )
    UpliftRevision.link_revision_to_assessment(other_revision["id"], colleagues)

    unrelated = UpliftAssessment.objects.create(
        user=user, bug_id=bug_id + 1, **UPLIFT_ASSESSMENT_FIELDS
    )

    response = authenticated_client.get(f"/D{revision['id']}/")

    assert response.status_code == 200, "The revision page should render."

    uplift = response.context_data["uplift"]
    assert uplift.bug_id == bug_id, "The page should know the revision's bug."

    cards = {card.assessment.id: card for card in uplift.bug_assessments}
    assert set(cards) == {linked.id, colleagues.id}, (
        "Both of the bug's assessments should be shown, and no others."
    )
    assert unrelated.id not in cards, (
        "An assessment for a different bug should not be shown."
    )
    assert cards[linked.id].is_linked, (
        "The assessment linked to this revision should be marked as linked."
    )
    assert not cards[colleagues.id].is_linked, (
        "A colleague's assessment linked elsewhere should not be marked as linked."
    )
    assert cards[colleagues.id].revision_ids == [other_revision["id"]], (
        "A card should list the revisions already carrying its assessment."
    )

    content = response.content.decode()
    assert "Uplift assessments for" in content, (
        "The section should be titled for the bug."
    )
    assert f"Create new assessment for bug {bug_id}" in content, (
        "The page should offer authoring a new assessment for the bug."
    )
    assert "Link to this revision" in content, (
        "An unlinked assessment should offer a link action."
    )
    for assessment_id in (linked.id, colleagues.id):
        assert f"Assessment #{assessment_id}" in content, (
            f"Assessment #{assessment_id} should be rendered as a card."
        )


@pytest.mark.django_db(transaction=True)
def test_stack_page_warns_when_the_revision_has_no_bug(
    authenticated_client,
    mocked_repo_config,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    scm_user,
):
    """Uplifts are tracked per bug, so a revision without one is called out."""
    phabrepo = phabdouble.repo(name="mozilla-uplift")
    revision = phabdouble.revision(repo=phabrepo)

    response = authenticated_client.get(f"/D{revision['id']}/")

    assert response.status_code == 200, "The revision page should still render."
    assert response.context_data["uplift"].bug_id is None, (
        "A revision without a bug number should report no bug."
    )

    content = response.content.decode()
    assert "This revision has no bug number." in content, (
        "The page should explain that a bug number is needed to uplift."
    )
    assert "Create new assessment for bug" not in content, (
        "Authoring an assessment should not be offered without a bug number."
    )
