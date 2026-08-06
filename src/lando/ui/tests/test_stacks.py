import pytest

from lando.api.support import LegacyAPIException
from lando.main.models import Revision
from lando.ui.stacks import (
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
