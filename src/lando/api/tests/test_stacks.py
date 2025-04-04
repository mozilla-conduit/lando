import pytest
from django.http import Http404

from lando.api.legacy.stacks import (
    RevisionStack,
    build_stack_graph,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)
from lando.api.legacy.transplants import (
    build_stack_assessment_state,
    run_landing_checks,
)
from lando.main.models import Repo
from lando.utils.phabricator import PhabricatorRevisionStatus


def test_build_stack_graph_single_node(phabdouble):
    revision = phabdouble.revision()

    nodes, edges = build_stack_graph(phabdouble.api_object_for(revision))
    assert len(nodes) == 1
    assert nodes.pop() == revision["phid"]
    assert not edges


def test_build_stack_graph_two_nodes(phabdouble):
    r1 = phabdouble.revision()
    r2 = phabdouble.revision(depends_on=[r1])

    nodes, edges = build_stack_graph(phabdouble.api_object_for(r1))
    assert nodes == {r1["phid"], r2["phid"]}
    assert len(edges) == 1
    assert edges == {(r2["phid"], r1["phid"])}

    # Building from either revision should result in same graph.
    nodes2, edges2 = build_stack_graph(phabdouble.api_object_for(r2))
    assert nodes2 == nodes
    assert edges2 == edges


def _build_revision_graph(phabdouble, dep_list):
    revisions = []

    for deps in dep_list:
        revisions.append(
            phabdouble.revision(depends_on=[revisions[dep] for dep in deps])
        )

    return revisions


def test_build_stack_graph_multi_root_multi_head_multi_path(phabdouble):
    # Revision stack to construct:
    # *     revisions[10]
    # | *   revisions[9]
    # |/
    # *     revisions[8]
    # |\
    # | *   revisions[7]
    # * |   revisions[6]
    # * |   revisions[5]
    # | *   revisions[4]
    # |/
    # *     revisions[3]
    # |\
    # | *   revisions[2]
    # | *   revisions[1]
    # *     revisions[0]

    # fmt: off
    revisions = _build_revision_graph(
        phabdouble, [
            [],
            [],
            [1],
            [0, 2],
            [3],
            [3],
            [5],
            [4],
            [6, 7],
            [8],
            [8],
        ]
    )
    # fmt: on

    nodes, edges = build_stack_graph(phabdouble.api_object_for(revisions[0]))
    assert nodes == {r["phid"] for r in revisions}
    assert edges == {
        (revisions[2]["phid"], revisions[1]["phid"]),
        (revisions[3]["phid"], revisions[2]["phid"]),
        (revisions[3]["phid"], revisions[0]["phid"]),
        (revisions[4]["phid"], revisions[3]["phid"]),
        (revisions[5]["phid"], revisions[3]["phid"]),
        (revisions[6]["phid"], revisions[5]["phid"]),
        (revisions[7]["phid"], revisions[4]["phid"]),
        (revisions[8]["phid"], revisions[6]["phid"]),
        (revisions[8]["phid"], revisions[7]["phid"]),
        (revisions[9]["phid"], revisions[8]["phid"]),
        (revisions[10]["phid"], revisions[8]["phid"]),
    }

    for r in revisions[1:]:
        nodes2, edges2 = build_stack_graph(phabdouble.api_object_for(r))
        assert nodes2 == nodes
        assert edges2 == edges


def test_build_stack_graph_disconnected_revisions_not_included(phabdouble):
    revisions = _build_revision_graph(
        phabdouble,
        [
            # Graph A.
            [],
            [0],
            [1],
            # Graph B.
            [],
            [3],
        ],
    )

    # Graph A.
    nodes, edges = build_stack_graph(phabdouble.api_object_for(revisions[0]))
    assert nodes == {r["phid"] for r in revisions[:3]}
    assert edges == {
        (revisions[1]["phid"], revisions[0]["phid"]),
        (revisions[2]["phid"], revisions[1]["phid"]),
    }

    # Graph B.
    nodes, edges = build_stack_graph(phabdouble.api_object_for(revisions[3]))
    assert nodes == {r["phid"] for r in revisions[3:]}
    assert edges == {(revisions[4]["phid"], revisions[3]["phid"])}


def test_request_extended_revision_data_single_revision_no_repo(phabdouble):
    phab = phabdouble.get_phabricator_client()

    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert diff["phid"] in data.diffs
    assert not data.repositories


def test_request_extended_revision_data_single_revision_with_repo(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert diff["phid"] in data.diffs
    assert repo["phid"] in data.repositories


def test_request_extended_revision_data_no_revisions(phabdouble):
    phab = phabdouble.get_phabricator_client()
    data = request_extended_revision_data(phab, [])

    assert not data.revisions
    assert not data.diffs
    assert not data.repositories


def test_request_extended_revision_data_gets_all_diffs(phabdouble):
    phab = phabdouble.get_phabricator_client()

    first_diff = phabdouble.diff()
    revision = phabdouble.revision(diff=first_diff)
    latest_diff = phabdouble.diff(revision=revision)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert first_diff["phid"] in data.diffs
    assert latest_diff["phid"] in data.diffs


def test_request_extended_revision_data_diff_and_revision_repo(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    repo2 = phabdouble.repo(name="repo2")
    diff = phabdouble.diff(repo=repo1)
    revision = phabdouble.revision(diff=diff, repo=repo2)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert diff["phid"] in data.diffs
    assert repo1["phid"] in data.repositories
    assert repo2["phid"] in data.repositories


def test_request_extended_revision_data_unrelated_revisions(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    diff1 = phabdouble.diff(repo=repo1)
    r1 = phabdouble.revision(diff=diff1, repo=repo1)

    repo2 = phabdouble.repo(name="repo2")
    diff2 = phabdouble.diff(repo=repo2)
    r2 = phabdouble.revision(diff=diff2, repo=repo2)

    data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    assert r1["phid"] in data.revisions
    assert r2["phid"] in data.revisions
    assert diff1["phid"] in data.diffs
    assert diff2["phid"] in data.diffs
    assert repo1["phid"] in data.repositories
    assert repo2["phid"] in data.repositories


def test_request_extended_revision_data_stacked_revisions(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()

    diff1 = phabdouble.diff(repo=repo)
    r1 = phabdouble.revision(diff=diff1, repo=repo)

    diff2 = phabdouble.diff(repo=repo)
    r2 = phabdouble.revision(depends_on=[r1], diff=diff2, repo=repo)

    data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    assert r1["phid"] in data.revisions
    assert r2["phid"] in data.revisions
    assert diff1["phid"] in data.diffs
    assert diff2["phid"] in data.diffs
    assert repo["phid"] in data.repositories

    data = request_extended_revision_data(phab, [r1["phid"]])

    assert r1["phid"] in data.revisions
    assert r2["phid"] not in data.revisions
    assert diff1["phid"] in data.diffs
    assert diff2["phid"] not in data.diffs
    assert repo["phid"] in data.repositories


def test_request_extended_revision_data_repo_has_projects(phabdouble, secure_project):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo(projects=[secure_project])

    diff1 = phabdouble.diff(repo=repo)
    r1 = phabdouble.revision(diff=diff1, repo=repo)

    data = request_extended_revision_data(phab, [r1["phid"]])

    assert all(
        "projects" in repo["attachments"] for repo in data.repositories.values()
    ), "`request_extended_revision_data` should return repos with `projects` attachment."


def test_request_extended_revision_data_raises_value_error(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])

    # Remove r2 from the list of revisions, keeping the dependency.
    phabdouble._revisions = [
        revision for revision in phabdouble._revisions if revision["id"] != r2["id"]
    ]

    with pytest.raises(ValueError) as e:
        request_extended_revision_data(phab, [r1["phid"], r2["phid"]])
    assert e.value.args[0] == "Mismatch in size of returned data."


@pytest.mark.django_db
def test_calculate_landable_subgraphs_no_edges_open(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    revision = phabdouble.revision(repo=repo)
    revision_obj = phabdouble.api_object_for(revision)
    ext_data = request_extended_revision_data(phab, [revision["phid"]])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(revision_obj)
    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()

    assert len(landable) == 1
    assert landable[0] == [revision["phid"]]


@pytest.mark.django_db
def test_calculate_landable_subgraphs_no_edges_closed(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    revision = phabdouble.revision(
        repo=repo, status=PhabricatorRevisionStatus.PUBLISHED
    )
    revision_obj = phabdouble.api_object_for(revision)
    ext_data = request_extended_revision_data(phab, [revision["phid"]])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(revision_obj)
    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()

    assert not landable


@pytest.mark.django_db
def test_calculate_landable_subgraphs_closed_root(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo, status=PhabricatorRevisionStatus.PUBLISHED)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    revision_obj = phabdouble.api_object_for(r1)

    ext_data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(revision_obj)
    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    assert landable == [[r2["phid"]]]


@pytest.mark.django_db
def test_calculate_landable_subgraphs_closed_root_child_merges(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, status=PhabricatorRevisionStatus.PUBLISHED)
    r4 = phabdouble.revision(repo=repo, depends_on=[r2, r3])
    revision_obj = phabdouble.api_object_for(r1)

    supported_repos = Repo.get_mapping()

    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"], r4["phid"]]
    )

    nodes, edges = build_stack_graph(revision_obj)
    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    assert [r3["phid"]] not in landable
    assert [r3["phid"], r4["phid"]] not in landable
    assert [r4["phid"]] not in landable
    assert landable == [[r1["phid"], r2["phid"], r4["phid"]]]


@pytest.mark.django_db
def test_calculate_landable_subgraphs_stops_multiple_repo_paths(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="mozilla-central")
    repo2 = phabdouble.repo(name="mozilla-new")
    r1 = phabdouble.revision(repo=repo1)
    r2 = phabdouble.revision(repo=repo1, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo2, depends_on=[r2])
    revision_obj = phabdouble.api_object_for(r1)

    supported_repos = Repo.get_mapping()

    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"]]
    )
    nodes, edges = build_stack_graph(revision_obj)
    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()

    assert landable == [[r1["phid"], r2["phid"]]]


@pytest.mark.django_db
def test_calculate_landable_subgraphs_allows_distinct_repo_paths(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="mozilla-central")
    r1 = phabdouble.revision(repo=repo1)
    r2 = phabdouble.revision(repo=repo1, depends_on=[r1])

    repo2 = phabdouble.repo(name="mozilla-new")
    r3 = phabdouble.revision(repo=repo2)
    r4 = phabdouble.revision(repo=repo2, depends_on=[r3])

    r5 = phabdouble.revision(repo=repo1, depends_on=[r2, r4])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(phabdouble.api_object_for(r1))
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"], r4["phid"], r5["phid"]]
    )
    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    assert len(landable) == 2
    assert [r1["phid"], r2["phid"]] in landable
    assert [r3["phid"], r4["phid"]] in landable


@pytest.mark.django_db
def test_calculate_landable_subgraphs_different_repo_parents(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="mozilla-central")
    r1 = phabdouble.revision(repo=repo1)

    repo2 = phabdouble.repo(name="mozilla-new")
    r2 = phabdouble.revision(repo=repo2)

    r3 = phabdouble.revision(repo=repo2, depends_on=[r1, r2])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(phabdouble.api_object_for(r1))
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"]]
    )

    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    assert len(landable) == 2
    assert [r1["phid"]] in landable
    assert [r2["phid"]] in landable


@pytest.mark.django_db
def test_calculate_landable_subgraphs_different_repo_closed_parent(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="mozilla-central")
    r1 = phabdouble.revision(repo=repo1, status=PhabricatorRevisionStatus.PUBLISHED)

    repo2 = phabdouble.repo(name="mozilla-new")
    r2 = phabdouble.revision(repo=repo2)

    r3 = phabdouble.revision(repo=repo2, depends_on=[r1, r2])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(phabdouble.api_object_for(r1))
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"]]
    )

    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    assert len(landable) == 1
    assert [r2["phid"], r3["phid"]] in landable


@pytest.mark.django_db
def test_calculate_landable_subgraphs_diverging_paths_merge(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)

    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r2])

    r4 = phabdouble.revision(repo=repo, depends_on=[r1])
    r5 = phabdouble.revision(repo=repo, depends_on=[r4])

    r6 = phabdouble.revision(repo=repo, depends_on=[r1])

    r7 = phabdouble.revision(repo=repo, depends_on=[r3, r5, r6])

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(phabdouble.api_object_for(r1))
    ext_data = request_extended_revision_data(
        phab,
        [
            r1["phid"],
            r2["phid"],
            r3["phid"],
            r4["phid"],
            r5["phid"],
            r6["phid"],
            r7["phid"],
        ],
    )

    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    assert len(landable) == 3
    assert [r1["phid"], r2["phid"], r3["phid"]] in landable
    assert [r1["phid"], r4["phid"], r5["phid"]] in landable
    assert [r1["phid"], r6["phid"]] in landable


@pytest.mark.django_db
def test_calculate_landable_subgraphs_complex_graph(
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    mocked_repo_config,
):
    phab = phabdouble.get_phabricator_client()

    repoA = phabdouble.repo(name="mozilla-central")
    repoB = phabdouble.repo(name="mozilla-new")
    repoC = phabdouble.repo(name="try")

    # Revision stack to construct:
    # *         rB4
    # |\
    # | *       rB3
    # * |       rB2 (CLOSED)
    #   | *     rC1
    #   |/
    #   *       rA10
    #  /|\
    # * | |     rB1
    #   | *     rA9 (CLOSED)
    #   *       rA8
    #   | *     rA7
    #   |/
    #   *       rA6
    #  /|
    # | *       rA5
    # | *       rA4
    # * |\      rA3 (CLOSED)
    # | * |     rA2
    #  \|/
    #   *       rA1 (CLOSED)

    rA1 = phabdouble.revision(repo=repoA, status=PhabricatorRevisionStatus.PUBLISHED)
    rA2 = phabdouble.revision(repo=repoA, depends_on=[rA1])
    rA3 = phabdouble.revision(
        repo=repoA, status=PhabricatorRevisionStatus.PUBLISHED, depends_on=[rA1]
    )
    rA4 = phabdouble.revision(repo=repoA, depends_on=[rA1, rA2])
    rA5 = phabdouble.revision(repo=repoA, depends_on=[rA4])
    rA6 = phabdouble.revision(repo=repoA, depends_on=[rA3, rA5])
    rA7 = phabdouble.revision(repo=repoA, depends_on=[rA6])
    rA8 = phabdouble.revision(repo=repoA, depends_on=[rA6])
    rA9 = phabdouble.revision(repo=repoA, status=PhabricatorRevisionStatus.PUBLISHED)

    rB1 = phabdouble.revision(repo=repoB)

    rA10 = phabdouble.revision(repo=repoA, depends_on=[rA8, rA9, rB1])

    rC1 = phabdouble.revision(repo=repoC, depends_on=[rA10])

    rB2 = phabdouble.revision(repo=repoB, status=PhabricatorRevisionStatus.PUBLISHED)
    rB3 = phabdouble.revision(repo=repoB, depends_on=[rA10])
    rB4 = phabdouble.revision(repo=repoB, depends_on=[rB2, rB3])

    nodes, edges = build_stack_graph(phabdouble.api_object_for(rA1))
    ext_data = request_extended_revision_data(
        phab,
        [
            rA1["phid"],
            rA2["phid"],
            rA3["phid"],
            rA4["phid"],
            rA5["phid"],
            rA6["phid"],
            rA7["phid"],
            rA8["phid"],
            rA9["phid"],
            rA10["phid"],
            rB1["phid"],
            rB2["phid"],
            rB3["phid"],
            rB4["phid"],
            rC1["phid"],
        ],
    )

    supported_repos = Repo.get_mapping()

    stack = RevisionStack(set(ext_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        ext_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()

    assert len(landable) == 3
    assert [rA2["phid"], rA4["phid"], rA5["phid"], rA6["phid"], rA7["phid"]] in landable
    assert [rA2["phid"], rA4["phid"], rA5["phid"], rA6["phid"], rA8["phid"]] in landable
    assert [rB1["phid"]] in landable


@pytest.mark.django_db
def test_calculate_landable_subgraphs_missing_repo(
    phabdouble, release_management_project, needs_data_classification_project
):
    """Test to assert a missing repository for a revision is
    blocked with an appropriate error
    """
    phab = phabdouble.get_phabricator_client()
    r1 = phabdouble.revision(repo=None)

    supported_repos = Repo.get_mapping()

    nodes, edges = build_stack_graph(phabdouble.api_object_for(r1))
    revision_data = request_extended_revision_data(phab, [r1["phid"]])

    stack = RevisionStack(set(revision_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        revision_data,
        stack,
        release_management_project["phid"],
        needs_data_classification_project["phid"],
    )
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()

    repo_unset_warning = (
        "Revision's repository unset. Specify a target using"
        '"Edit revision" in Phabricator'
    )

    assert not landable
    assert r1["phid"] not in stack_state.landable_stack
    assert repo_unset_warning in stack_state.stack.nodes[r1["phid"]]["blocked"]


@pytest.mark.django_db
def test_get_landable_repos_for_revision_data(phabdouble, mocked_repo_config):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="mozilla-central")
    repo2 = phabdouble.repo(name="not-mozilla-central")
    r1 = phabdouble.revision(repo=repo1)
    r2 = phabdouble.revision(repo=repo2, depends_on=[r1])

    supported_repos = Repo.get_mapping()
    revision_data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    landable_repos = get_landable_repos_for_revision_data(
        revision_data, supported_repos
    )
    assert repo1["phid"] in landable_repos
    assert repo2["phid"] not in landable_repos
    assert landable_repos[repo1["phid"]].tree == "mozilla-central"


@pytest.mark.django_db
def test_integrated_stack_endpoint_simple(
    proxy_client,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
    secure_project,
):
    repo = phabdouble.repo()
    unsupported_repo = phabdouble.repo(name="not-mozilla-central")
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r1])
    r4 = phabdouble.revision(repo=unsupported_repo, depends_on=[r2, r3])

    response = proxy_client.get("/stacks/D{}".format(r3["id"]))
    assert response.status_code == 200

    assert len(response.json["edges"]) == 4
    assert [r2["phid"], r1["phid"]] in response.json["edges"]
    assert [r3["phid"], r1["phid"]] in response.json["edges"]
    assert [r4["phid"], r2["phid"]] in response.json["edges"]
    assert [r4["phid"], r3["phid"]] in response.json["edges"]

    assert len(response.json["landable_paths"]) == 2
    assert [r1["phid"], r2["phid"]] in response.json["landable_paths"]
    assert [r1["phid"], r3["phid"]] in response.json["landable_paths"]

    assert len(response.json["revisions"]) == 4
    revisions = {r["phid"]: r for r in response.json["revisions"]}
    assert r1["phid"] in revisions
    assert r2["phid"] in revisions
    assert r3["phid"] in revisions
    assert r4["phid"] in revisions

    assert revisions[r4["phid"]]["blocked_reasons"] == [
        "Repository is not supported by Lando."
    ]


@pytest.mark.django_db
def test_integrated_stack_endpoint_repos(
    proxy_client,
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
):
    repo = phabdouble.repo()
    unsupported_repo = phabdouble.repo(name="not-mozilla-central")
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r1])
    r4 = phabdouble.revision(repo=unsupported_repo, depends_on=[r2, r3])

    response = proxy_client.get("/stacks/D{}".format(r4["id"]))
    assert response.status_code == 200

    assert len(response.json["repositories"]) == 2

    repositories = {r["phid"]: r for r in response.json["repositories"]}
    assert repo["phid"] in repositories
    assert unsupported_repo["phid"] in repositories
    assert repositories[repo["phid"]]["landing_supported"]
    assert not repositories[unsupported_repo["phid"]]["landing_supported"]
    assert repositories[repo["phid"]]["url"] == "http://hg.test"
    assert repositories[unsupported_repo["phid"]]["url"] == (
        "http://phabricator.test/source/not-mozilla-central"
    )


@pytest.mark.django_db
def test_integrated_stack_has_revision_security_status(
    proxy_client,
    phabdouble,
    mock_repo_config,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
    secure_project,
):
    repo = phabdouble.repo()
    public_revision = phabdouble.revision(repo=repo)
    secure_revision = phabdouble.revision(
        repo=repo, projects=[secure_project], depends_on=[public_revision]
    )

    response = proxy_client.get("/stacks/D{}".format(secure_revision["id"]))
    assert response.status_code == 200

    revisions = {r["phid"]: r for r in response.json["revisions"]}
    assert not revisions[public_revision["phid"]]["is_secure"]
    assert revisions[secure_revision["phid"]]["is_secure"]


@pytest.mark.django_db
def test_integrated_stack_response_mismatch_returns_404(
    proxy_client,
    phabdouble,
    mock_repo_config,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
    secure_project,
):
    # If the API response contains a different number of revisions than the
    # expected number based on the stack graph, a 404 error is expected.

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])

    response = proxy_client.get("/stacks/D{}".format(r1["id"]))
    assert response.status_code == 200
    assert len(response.json["edges"]) == 1
    assert len(response.json["revisions"]) == 2

    # Remove r2 from the response.
    phabdouble._revisions = [
        revision for revision in phabdouble._revisions if revision["id"] != r2["id"]
    ]

    with pytest.raises(Http404):
        response = proxy_client.get("/stacks/D{}".format(r1["id"]))

    # Remove dependency on r2.
    phabdouble.update_revision_dependencies(r1["phid"], [])

    response = proxy_client.get("/stacks/D{}".format(r1["id"]))
    assert response.status_code == 200
    assert len(response.json["edges"]) == 0
    assert len(response.json["revisions"]) == 1


def test_revisionstack_single():
    nodes = {"123"}
    edges = set()

    stack = RevisionStack(nodes, edges)

    assert list(stack.root_revisions()) == [
        "123"
    ], "Node `123` should be the root revision."

    assert list(stack.iter_stack_from_root("123")) == [
        "123",
    ], "Iterating over the stack from the root should return the revision."


def test_revisionstack_stack():
    nodes = {"123", "456", "789"}
    edges = {("123", "456"), ("456", "789")}

    stack = RevisionStack(nodes, edges)

    assert list(stack.root_revisions()) == [
        "789"
    ], "Node `789` should be the root revision."

    assert list(stack.leaf_revisions()) == [
        "123"
    ], "Node `123` should be the only leaf revisions."

    assert list(stack.iter_stack_from_root("123")) == ["789", "456", "123"], (
        "Iterating over the stack from the root to the tip should "
        "result in the full graph as the response."
    )

    assert list(stack.iter_stack_from_root("456")) == ["789", "456"], (
        "Iterating over the stack from the root to a non-tip node should "
        "result in only the path from root to `head` as the response."
    )
