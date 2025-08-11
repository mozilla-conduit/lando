import datetime

import pytest

from lando.treestatus.models import CombinedTree, TreeCategory, TreeStatus
from lando.treestatus.views.api import (
    LogEntry,
    StackEntry,
    TreeData,
    apply_log_and_stack_update,
    apply_status_change_update,
    apply_tree_updates,
    create_new_tree,
    get_combined_tree,
    is_open,
    remove_tree_by_name,
    revert_status_change,
)
from lando.utils.exceptions import ProblemException


class IncreasingDatetime:
    """Return an object that returns datetimes with increasing times."""

    def __init__(self, initial_time: datetime.datetime = datetime.datetime.min):
        self.current_datetime = initial_time

    def __call__(self, *args, **kwargs) -> datetime.datetime:
        increased_datetime = self.current_datetime + datetime.timedelta(minutes=10)
        self.current_datetime = increased_datetime
        return increased_datetime


@pytest.mark.django_db
def test_is_open_assumes_true_on_unknown_tree():
    assert is_open(
        "tree-doesn't-exist"
    ), "`is_open` should return `True` for unknown tree."


@pytest.mark.django_db
def test_is_open_for_open_tree(new_treestatus_tree):
    new_treestatus_tree(tree="mozilla-central", status=TreeStatus.OPEN)
    assert is_open("mozilla-central"), "`is_open` should return `True` for opened tree."


@pytest.mark.django_db
def test_is_open_for_closed_tree(new_treestatus_tree):
    new_treestatus_tree(tree="mozilla-central", status=TreeStatus.CLOSED)
    assert not is_open(
        "mozilla-central"
    ), "`is_open` should return `False` for closed tree."


@pytest.mark.django_db
def test_is_open_for_approval_required_tree(new_treestatus_tree):
    new_treestatus_tree(tree="mozilla-central", status=TreeStatus.APPROVAL_REQUIRED)
    assert is_open(
        "mozilla-central"
    ), "`is_open` should return `True` for approval required tree."


@pytest.mark.django_db
def test_get_combined_tree(new_treestatus_tree):
    tree = new_treestatus_tree(
        motd="message",
        reason="reason",
        status=TreeStatus.OPEN,
        tree="mozilla-central",
    )

    assert get_combined_tree(tree) == CombinedTree(
        category=TreeCategory.OTHER,
        log_id=None,
        message_of_the_day="message",
        instance=tree,
        reason="reason",
        status=TreeStatus.OPEN,
        tags=[],
        tree="mozilla-central",
    ), "Combined tree does not match expected."


@pytest.mark.django_db
def test_get_tree_exists(client, new_treestatus_tree):
    tree = new_treestatus_tree(
        tree="mozilla-central", status=TreeStatus.OPEN, reason="reason", motd="message"
    )
    response = client.get("/trees/mozilla-central")
    assert (
        "result" in response.json()
    ), "Response should be contained in the `result` key."
    assert response.status_code == 200, "Response status code should be 200."

    tree_response = TreeData(**response.json()["result"])
    assert (
        tree_response.tree == tree.tree
    ), "Returned `tree` should be `mozilla-central`."
    assert (
        tree_response.message_of_the_day == tree.message_of_the_day
    ), "Returned `message_of_the_day` should be `message`."
    assert tree_response.reason == tree.reason, "Returned `reason` should be `reason`."
    assert tree_response.status == tree.status, "Returned `status` should be `open`."


@pytest.mark.django_db
def test_get_tree_missing(client):
    response = client.get("/trees/missingtree")

    assert response.status_code == 404

    json = response.json()
    assert json["title"] == "No tree missingtree found."
    assert json["detail"] == "The tree does not exist."
    assert json["status"] == 404


@pytest.mark.django_db
def test_api_get_trees2(client, new_treestatus_tree):
    """API test for `GET /trees2`."""
    response = client.get("/trees2")
    assert (
        response.status_code == 200
    ), "`GET /trees2` should return 200 even when no trees are found."
    assert "result" in response.json(), "Response should contain `result` key."
    assert response.json()["result"] == [], "Result from Treestatus should be empty."

    new_treestatus_tree(tree="mozilla-central")
    response = client.get("/trees2")
    assert (
        response.status_code == 200
    ), "`GET /trees2` should return 200 when trees are found."
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 1, "Result from Treestatus should contain one tree"
    assert TreeData(**result[0]), "Response should match expected tree format."


@pytest.mark.django_db
def test_api_get_logs(client, new_treestatus_tree):
    """API test for `GET /trees/{tree}/logs`."""

    def patch_tree(body):
        """Convenience closure to patch the tree."""
        apply_tree_updates(
            user_id="ad|Example-LDAP|testuser",
            trees=body["trees"],
            status=TreeStatus(body["status"]),
            tags=body["tags"],
            reason=body["reason"],
            remember=True,
        )

    # Create a new tree.
    new_treestatus_tree(tree="tree", status=TreeStatus.CLOSED)

    # Update status.
    patch_tree(
        {
            "reason": "first open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "first close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )
    patch_tree(
        {
            "reason": "second open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "second close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )
    patch_tree(
        {
            "reason": "third open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "third close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )
    patch_tree(
        {
            "reason": "fourth open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "fourth close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )

    # Check the most recent logs are returned.
    response = client.get("/trees/tree/logs")

    assert response.status_code == 200, "Requesting all logs should return `200`."
    result = response.json().get("result")
    assert result is not None, "Response JSON should contain `result` key."
    assert len(result) == 5, "`logs` endpoint should only return latest logs."
    expected_keys = [
        {
            "id": 8,
            "reason": "fourth close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 7,
            "reason": "fourth open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 6,
            "reason": "third close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 5,
            "reason": "third open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 4,
            "reason": "second close",
            "status": "closed",
            "tags": ["sometag1"],
        },
    ]

    for tree, expected in zip(result, expected_keys, strict=False):
        tree_data = LogEntry(**tree)
        assert tree_data.id == expected["id"], "ID should match expected."
        assert tree_data.reason == expected["reason"], "Reason should match expected."
        assert tree_data.status == expected["status"], "Status should match expected."
        assert sorted(tree_data.tags) == sorted(
            expected["tags"]
        ), "Tags should match expected."

    # Check all results are returned from `logs_all`.
    response = client.get("/trees/tree/logs_all")

    assert response.status_code == 200, "Requesting all logs should return `200`."
    result = response.json().get("result")
    assert result is not None, "Response JSON should contain `result` key."
    expected_keys = [
        {
            "id": 8,
            "reason": "fourth close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 7,
            "reason": "fourth open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 6,
            "reason": "third close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 5,
            "reason": "third open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 4,
            "reason": "second close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 3,
            "reason": "second open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 2,
            "reason": "first close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 1,
            "reason": "first open",
            "status": "open",
            "tags": [],
        },
    ]
    for tree, expected in zip(result, expected_keys, strict=False):
        tree_data = LogEntry(**tree)
        assert tree_data.id == expected["id"], "ID should match expected."
        assert tree_data.reason == expected["reason"], "Reason should match expected."
        assert tree_data.status == expected["status"], "Status should match expected."
        assert sorted(tree_data.tags) == sorted(
            expected["tags"]
        ), "Tags should match expected."


@pytest.mark.django_db
def test_remove_tree_by_name_unknown():
    """API test for `DELETE /trees/{tree}` with an unknown tree."""
    with pytest.raises(ProblemException) as exc_info:
        remove_tree_by_name(tree_name="unknowntree")

    exc = exc_info.value

    assert exc.problem.detail == "The tree does not exist."
    assert exc.problem.status == 404
    assert exc.problem.title == "No tree unknowntree found."
    assert (
        exc.problem.type
        == "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404"
    )


@pytest.mark.django_db
def test_remove_tree_by_name_known(client, new_treestatus_tree):
    """API test for `DELETE /trees/{tree}` with a known tree."""
    new_treestatus_tree(tree="mozilla-central")

    # Delete the tree.
    remove_tree_by_name(tree_name="mozilla-central")

    # Check that tree is deleted.
    response = client.get("/trees/mozilla-central")
    assert response.status_code == 404, "Tree should be Not Found after delete."


@pytest.mark.django_db
def test_make_tree(client):
    """API test for `PUT /trees/{tree}`."""
    # Tree can be added as expected.
    create_new_tree(
        user_id="", tree="tree", category=TreeCategory.OTHER, status=TreeStatus.OPEN
    )

    # Tree can be retrieved from the API after being added.
    response = client.get("/trees/tree")
    assert (
        response.status_code == 200
    ), "Retrieving tree after addition should return 200 status code."
    result = response.json().get("result")
    assert result is not None, "Response should contain a `result` key."
    tree_data = TreeData(**result)
    assert (
        tree_data.status == "open"
    ), "Status should be retrievable after tree creation."

    # Attempt to add a duplicate tree.
    with pytest.raises(ProblemException) as exc_info:
        create_new_tree(
            user_id="", tree="tree", category=TreeCategory.OTHER, status=TreeStatus.OPEN
        )

    exc = exc_info.value

    assert exc.problem.status == 400
    assert exc.problem.title == "Tree already exists."
    assert exc.problem.detail == "Tree tree already exists."
    assert (
        exc.problem.type
        == "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400"
    )


@pytest.mark.django_db
def test_api_get_trees_single_not_found(client):
    """API test for `GET /trees/{tree}` with an unknown tree."""
    response = client.get("/trees/unknowntree")
    assert (
        response.status_code == 404
    ), "Response code for unknown tree should be `404`."
    assert response.json() == {
        "detail": "The tree does not exist.",
        "status": 404,
        "title": "No tree unknowntree found.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
    }, "Response JSON for missing result should match expected value."


@pytest.mark.django_db
def test_api_get_trees_single_exists(client, new_treestatus_tree):
    """API test for `GET /trees/{tree}` with a known tree."""
    new_treestatus_tree(tree="mozilla-central")

    response = client.get("/trees/mozilla-central")
    assert (
        response.status_code == 200
    ), "Response code when a tree is found should be `200`."
    result = response.json().get("result")
    assert result is not None, "Response JSON should contain `result` key."
    get_data = TreeData(**result)
    assert get_data.tree == "mozilla-central", "Tree name should match expected"


@pytest.mark.django_db
def test_apply_tree_updates_unknown_tree(new_treestatus_tree):
    """API test for `PATCH /trees` with unknown tree name."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    # Pass a tree that doesn't exist.
    with pytest.raises(ProblemException) as exc_info:
        apply_tree_updates(user_id="", trees=["badtree"])

    exc = exc_info.value

    assert exc.problem.status == 404
    assert exc.problem.detail == "Could not fetch all the requested trees."
    assert exc.problem.title == "Could not fetch the following trees: badtree"


@pytest.mark.django_db
def test_apply_tree_updates_tags_required(new_treestatus_tree):
    """API test for `PATCH /trees` with missing tags when closing."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    # Tags are required when closing a tree.
    with pytest.raises(ProblemException) as exc_info:
        apply_tree_updates(
            user_id="", trees=["autoland", "mozilla-central"], status=TreeStatus.CLOSED
        )

    exc = exc_info.value

    assert exc.problem.status == 400
    assert exc.problem.detail == "Tags are required when closing a tree."
    assert exc.problem.title == "Tags are required when closing a tree."


@pytest.mark.django_db
def test_apply_tree_updates_remember_required_args(new_treestatus_tree):
    """API test for `PATCH /trees` required args with `remember`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    # Remember == True requires status.
    with pytest.raises(ProblemException) as exc_info:
        apply_tree_updates(
            user_id="",
            remember=True,
            reason="somereason",
            tags=["sometag1", "sometag2"],
            trees=["autoland", "mozilla-central"],
        )

    exc = exc_info.value

    assert (
        exc.problem.detail
        == "Must specify status, reason and tags to remember the change."
    )

    assert exc.problem.status == 400
    assert (
        exc.problem.title
        == "Must specify status, reason and tags to remember the change."
    )
    assert (
        exc.problem.type
        == "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400"
    )

    # Remember == True requires reason.
    with pytest.raises(ProblemException) as exc_info:
        apply_tree_updates(
            user_id="",
            remember=True,
            status=TreeStatus.OPEN,
            tags=["sometag1", "sometag2"],
            trees=["autoland", "mozilla-central"],
        )

    exc = exc_info.value

    assert (
        exc.problem.detail
        == "Must specify status, reason and tags to remember the change."
    )
    assert exc.problem.status == 400
    assert (
        exc.problem.title
        == "Must specify status, reason and tags to remember the change."
    )
    assert (
        exc.problem.type
        == "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400"
    )

    # Remember == True requires tags.
    with pytest.raises(ProblemException) as exc_info:
        apply_tree_updates(
            user_id="",
            remember=True,
            reason="somereason",
            status=TreeStatus.OPEN,
            trees=["autoland", "mozilla-central"],
        )

    exc = exc_info.value

    assert (
        exc.problem.detail
        == "Must specify status, reason and tags to remember the change."
    )
    assert exc.problem.status == 400
    assert (
        exc.problem.title
        == "Must specify status, reason and tags to remember the change."
    )
    assert (
        exc.problem.type
        == "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400"
    )


@pytest.mark.django_db
def test_apply_tree_updates_success_remember(client, new_treestatus_tree):
    """API test for `PATCH /trees` success with `remember: true`."""
    tree_names = ["autoland", "mozilla-central"]
    for tree in tree_names:
        new_treestatus_tree(tree=tree)

    apply_tree_updates(
        user_id="",
        remember=True,
        reason="somereason",
        status=TreeStatus.CLOSED,
        tags=["sometag1", "sometag2"],
        trees=tree_names,
    )

    # Ensure the statuses were both updated as expected.
    response = client.get("/trees")
    result = response.json().get("result")
    assert result is not None, "Response should contain a `result` key."

    assert all(tree in result for tree in tree_names), "Both trees should be returned."

    for info in result.values():
        tree_data = TreeData(**info)

        assert tree_data.status == "closed", "Tree status should be set to closed."
        assert tree_data.reason == "somereason", "Tree reason should be set."

    response = client.get("/stack")
    assert response.status_code == 200

    result = response.json().get("result")
    assert result is not None, "Response should contain a `result` key."
    assert (
        len(result) == 1
    ), "Setting `remember: true` should have created a stack entry."

    stack_entry = StackEntry(**result[0])
    assert (
        stack_entry.reason == "somereason"
    ), "Stack entry reason should match expected."
    assert stack_entry.status == "closed", "Stack entry status should match expected."

    for tree in stack_entry.trees:
        assert tree.last_state.current_reason == "somereason"
        assert tree.last_state.current_status == "closed"
        assert tree.last_state.reason == ""
        assert tree.last_state.status == "open"


@pytest.mark.django_db
def test_apply_tree_updates_success_no_remember(client, new_treestatus_tree):
    """API test for `PATCH /trees` success with `remember: false`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    apply_tree_updates(
        user_id="",
        reason="somereason",
        status=TreeStatus.CLOSED,
        tags=["sometag1", "sometag2"],
        trees=["autoland", "mozilla-central"],
    )

    # Ensure the statuses were both updated as expected.
    response = client.get("/trees")
    result = response.json().get("result")
    assert result is not None, "Response should contain a result key."
    assert len(result) == 2, "Two trees should be returned."
    for tree in result.values():
        tree_data = TreeData(**tree)

        assert tree_data.reason == "somereason", "Status should be updated on the tree."
        assert tree_data.status == "closed", "Status should be updated on the tree."

    response = client.get("/stack")
    assert response.status_code == 200
    assert (
        response.json()["result"] == []
    ), "Status should not have been added to the stack."


@pytest.mark.django_db
def test_api_get_trees(client, new_treestatus_tree):
    """API test for `GET /trees`."""
    response = client.get("/trees")
    assert (
        response.status_code == 200
    ), "`GET /trees` should return 200 even when no trees are found."
    assert "result" in response.json(), "Response should contain `result` key."
    assert response.json()["result"] == {}, "Result from Treestatus should be empty."

    new_treestatus_tree(tree="mozilla-central")
    response = client.get("/trees")
    assert (
        response.status_code == 200
    ), "`GET /trees` should return 200 when trees are found."
    result = response.json().get("result")
    assert result is not None, "Response should contain a result key."
    assert len(result) == 1, "Result from Treestatus should contain one tree."

    tree = result.get("mozilla-central")
    assert tree is not None, "mozilla-central tree should be present in response."
    assert TreeData(**tree), "Tree response should match expected format."


@pytest.mark.django_db
def test_revert_change_revert(client, new_treestatus_tree):
    """API test for `DELETE /stack/{id}` with `revert=1`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    apply_tree_updates(
        user_id="",
        remember=True,
        reason="some reason for opening",
        status=TreeStatus.OPEN,
        tags=["sometag1", "sometag2"],
        trees=["autoland", "mozilla-central"],
    )

    apply_tree_updates(
        user_id="",
        remember=True,
        reason="some reason to close",
        status=TreeStatus.CLOSED,
        tags=["closingtag1", "closingtag2"],
        trees=["autoland", "mozilla-central"],
    )

    response = client.get("/stack")

    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 2, "Both tree status updates should be on the stack."

    latest_stack_entry = max(
        (StackEntry(**entry) for entry in result),
        key=lambda stack_entry: stack_entry.id,
    )

    # Assert the state of stack entry 2 is correct, since we will be restoring it.
    assert latest_stack_entry.reason == "some reason to close"
    assert latest_stack_entry.status == "closed"
    assert len(latest_stack_entry.trees) == 2

    for tree in latest_stack_entry.trees:
        assert tree.last_state.current_status == "closed"
        assert tree.last_state.current_reason == "some reason to close"
        assert tree.last_state.status == "open"
        assert tree.last_state.reason == "some reason for opening"
        assert sorted(tree.last_state.tags) == ["sometag1", "sometag2"]

    revert_status_change(latest_stack_entry.id, "user@example.com", revert=True)

    response = client.get("/stack")
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 1, "Restoring stack should remove a stack entry."

    # Check current tree state.
    response = client.get("/trees/autoland")
    assert response.status_code == 200
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    tree_state = TreeData(**result)
    assert (
        tree_state.reason == "some reason for opening"
    ), "Previous reason should be restored."
    assert tree_state.status == "open", "Previous state should be restored."
    assert sorted(tree_state.tags) == [
        "sometag1",
        "sometag2",
    ], "Previous tags should be restored."


@pytest.mark.django_db
def test_revert_change_no_revert(client, new_treestatus_tree):
    """API test for `DELETE /stack/{id}` with `revert=0`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    apply_tree_updates(
        user_id="",
        remember=True,
        reason="some reason for opening",
        status=TreeStatus.OPEN,
        tags=["sometag1", "sometag2"],
        trees=["autoland", "mozilla-central"],
    )

    apply_tree_updates(
        user_id="",
        remember=True,
        reason="some reason to close",
        status=TreeStatus.CLOSED,
        tags=["closingtag1", "closingtag2"],
        trees=["autoland", "mozilla-central"],
    )

    response = client.get("/stack")

    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 2, "Both tree status updates should be on the stack."

    latest_stack_entry = max(
        (StackEntry(**entry) for entry in result),
        key=lambda stack_entry: stack_entry.id,
    )

    # Assert the state of stack entry 2 is correct, since we will be deleting it.
    assert latest_stack_entry.reason == "some reason to close"
    assert latest_stack_entry.status == "closed"
    assert len(latest_stack_entry.trees) == 2

    for tree in latest_stack_entry.trees:
        assert tree.last_state.current_status == "closed"
        assert tree.last_state.current_reason == "some reason to close"
        assert tree.last_state.status == "open"
        assert tree.last_state.reason == "some reason for opening"
        assert sorted(tree.last_state.tags) == ["sometag1", "sometag2"]

    revert_status_change(latest_stack_entry.id, "user@example.com", revert=False)

    response = client.get("/stack")
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 1, "Discarding should remove an entry from the stack."

    response = client.get("/trees/autoland")
    assert response.status_code == 200

    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    tree_state = TreeData(**result)
    assert (
        tree_state.reason == "some reason to close"
    ), "Reason should be preserved after discard."
    assert (
        tree_state.status == "closed"
    ), "Tree status should be preserved after discard."
    assert sorted(tree_state.tags) == [
        "closingtag1",
        "closingtag2",
    ], "Tags should be preserved after discard."


@pytest.mark.django_db
def test_update_status_change(client, new_treestatus_tree):
    """API test for `PATCH /stack/{id}`."""
    new_treestatus_tree(tree="autoland")

    # Set the tree to open.
    apply_tree_updates(
        user_id="",
        remember=True,
        reason="some reason for opening",
        status=TreeStatus.OPEN,
        tags=["sometag1", "sometag2"],
        trees=["autoland"],
    )

    # Set the tree to closed.
    apply_tree_updates(
        user_id="",
        remember=True,
        reason="the tree is closed.",
        status=TreeStatus.CLOSED,
        tags=["closed tree"],
        trees=["autoland"],
    )

    # Get information about the stack.
    response = client.get("/stack")
    assert response.status_code == 200

    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 2, "Stack should contain two entries."

    earliest_stack_entry = min(
        (StackEntry(**entry) for entry in result),
        key=lambda stack_entry: stack_entry.id,
    )

    assert earliest_stack_entry.reason == "some reason for opening"
    assert sorted(earliest_stack_entry.trees[0].last_state.current_tags) == [
        "sometag1",
        "sometag2",
    ]

    # Patch the stack.
    apply_status_change_update(
        id=earliest_stack_entry.id, reason="updated reason", tags=["updated tags"]
    )

    # Check the stack has been updated.
    response = client.get("/stack")
    assert response.status_code == 200
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."

    earliest_stack_entry = min(
        (StackEntry(**entry) for entry in result),
        key=lambda stack_entry: stack_entry.id,
    )

    assert earliest_stack_entry.reason == "updated reason"
    assert earliest_stack_entry.trees[0].last_state.current_reason == "updated reason"
    assert sorted(earliest_stack_entry.trees[0].last_state.current_tags) == [
        "updated tags",
    ]


@pytest.mark.django_db
def test_update_log_and_stack(client, new_treestatus_tree):
    """API test for `PATCH /log/{id}`."""
    new_treestatus_tree(tree="autoland")

    apply_tree_updates(
        user_id="",
        remember=True,
        reason="some reason for closing",
        status=TreeStatus.CLOSED,
        tags=["sometag1", "sometag2"],
        trees=["autoland"],
    )

    response = client.get("/trees/autoland/logs")

    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."

    log = LogEntry(**result[0])

    apply_log_and_stack_update(log_id=log.id, reason="new log reason")

    apply_log_and_stack_update(log_id=log.id, tags=["new tag 1", "new tag 2"])

    response = client.get("/trees/autoland/logs")
    assert response.status_code == 200

    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."

    log = LogEntry(**result[0])
    assert log.reason == "new log reason", "Fetching logs should show updated reason."
    assert log.tags == [
        "new tag 1",
        "new tag 2",
    ], "Fetching logs should show updated tags."

    response = client.get("/stack")
    assert response.status_code == 200
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."

    stack_entry = StackEntry(**result[0])
    stack_tree = stack_entry.trees[0].last_state
    assert (
        stack_tree.current_reason == "new log reason"
    ), "Stack should show updated log reason."
    assert stack_tree.current_tags == [
        "new tag 1",
        "new tag 2",
    ], "Stack should show updated log tags."


@pytest.mark.django_db
def test_api_get_stack(client, new_treestatus_tree):
    """API test for `GET /stack`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    apply_tree_updates(
        user_id="ad|Example-LDAP|testuser",
        trees=["autoland", "mozilla-central"],
        status=TreeStatus.OPEN,
        tags=["sometag1", "sometag2"],
        reason="some reason for opening",
        remember=True,
    )

    apply_tree_updates(
        user_id="ad|Example-LDAP|testuser",
        trees=["autoland", "mozilla-central"],
        status=TreeStatus.CLOSED,
        tags=["closingtag1", "closingtag2"],
        reason="some reason to close",
        remember=True,
    )

    response = client.get("/stack")
    assert response.status_code == 200
    result = response.json().get("result")
    assert result is not None, "Response should contain `result` key."
    for entry in result:
        assert StackEntry(**entry)
