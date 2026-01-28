from unittest.mock import MagicMock

import pytest

from lando.api.legacy.stacks import RevisionStack
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
        revision_repo=None,
        revision_id=revision_id,
        revision_phid=revision_phid,
        revisions=revisions,
        stack=mock_stack,
    )

    assert context.request_form.initial["source_revisions"] == [
        revision_id
    ], "Form should be initialized with current revision."


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
        revision_repo=None,
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
