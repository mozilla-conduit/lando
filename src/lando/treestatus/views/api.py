import functools
import logging
from datetime import datetime
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    TypeVar,
)

from django.core.cache import cache
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import OuterRef, Subquery
from django.db.utils import IntegrityError
from ninja import NinjaAPI, Schema
from ninja.responses import Response, codes_4xx

from lando.treestatus.models import (
    CombinedTree,
    Log,
    StatusChange,
    StatusChangeTree,
    Tree,
    TreeCategory,
    TreeStatus,
    get_default_tree,
    load_last_state,
)
from lando.utils.cache import cache_method
from lando.utils.exceptions import (
    BadRequestProblemException,
    NotFoundProblemException,
    ProblemDetail,
    ProblemException,
)

logger = logging.getLogger(__name__)

treestatus_api = NinjaAPI(auth=None, urls_namespace="treestatus-api")

TREE_SUMMARY_LOG_LIMIT = 5


@treestatus_api.exception_handler(ProblemException)
def problem_exception_handler(request: WSGIRequest, exc: ProblemException) -> Response:
    """Convert a thrown `ProblemException` to a response."""
    return Response(
        exc.to_response(),
        status=exc.status_code,
        content_type="application/problem+json",
    )


# Generic type variable for the data contained in a result field.
# This allows `Result[T]` to wrap any response schema. For example,
# `Result[list[TreeData]]` meaning a list of `TreeData` responses
# wrapped in a `result` object.
T = TypeVar("T")


class Result(Schema, Generic[T]):
    """Result wrapper for API responses."""

    result: T


class TreeData(Schema):
    """Expected schema of a tree."""

    category: Optional[str]
    log_id: Optional[int]
    message_of_the_day: str
    reason: str
    status: TreeStatus
    tags: list[str]
    tree: str


class LogEntry(Schema):
    """Expected schema of a log entry."""

    id: int
    reason: str
    status: str
    tags: list[str]
    tree: str
    when: datetime
    who: str


class LastState(Schema):
    """Expected schema for a "last state" object."""

    log_id: Optional[int]
    reason: str
    status: str
    tags: list[str]
    current_log_id: Optional[int]
    current_reason: str
    current_status: str
    current_tags: list[str]


class TreesEntry(Schema):
    """Expected schema for a "trees" entry in the stack."""

    id: int
    last_state: LastState
    tree: str


class StackEntry(Schema):
    """Expected schema of a stack entry."""

    id: int
    reason: str
    status: str
    trees: list[TreesEntry]
    when: datetime
    who: str


def get_combined_tree(
    tree: Tree,
    tags: Optional[list[str]] = None,
    status: Optional[TreeStatus] = None,
    reason: Optional[str] = None,
    log_id: Optional[int] = None,
) -> CombinedTree:
    """Combined view of the Tree.

    This also shows status, reason and tags from last Tree Log.
    """
    result = get_default_tree()
    result.update(tree.to_dict())

    if tags is not None:
        result["tags"] = tags

    if status is not None:
        result["status"] = TreeStatus(status)

    if reason is not None:
        result["reason"] = reason

    if log_id is not None:
        result["log_id"] = log_id

    result["instance"] = tree

    return CombinedTree(**result)


def result_object_wrap(func: Callable) -> Callable:
    """Wrap the value returned from `f` in a result dict.

    Return a result wrapped in a dict with a `result` key, like so:
        {"result": ...}
    """

    @functools.wraps(func)
    def wrap_output(*args, **kwargs) -> Result:
        result = func(*args, **kwargs)
        return Result(result=result)

    return wrap_output


def serialize_last_state(old_tree: dict, new_tree: CombinedTree) -> dict[str, Any]:
    """Serialize a `last_state` value for a `StatusChangeTree`.

    Given a `dict` representing the old state of a tree and a `CombinedTree`
    representing the current state, return a `dict` describing the change in
    state that can be stored in a `StatusChangeTree` for use in restoring the
    previous state.
    """
    return {
        "status": old_tree["status"].value,
        "reason": old_tree["reason"],
        "tags": old_tree["tags"],
        "log_id": old_tree["log_id"],
        "current_status": new_tree.status.value,
        "current_reason": new_tree.reason,
        "current_tags": new_tree.tags,
        "current_log_id": new_tree.log_id,
    }


def is_open(tree_name: str) -> bool:
    """Return `True` if the tree is considered open for landing.

    The tree is open for landing when it is `open` or `approval required`.
    If the tree cannot be found in Treestatus it is considered open.
    """
    tree = get_tree_by_name(tree_name)

    # We assume missing trees are open.
    return not tree or tree.status.is_open()


def tree_cache_key(tree_name: str) -> str:
    """Return the cache key for this tree name."""
    return f"tree-cache-{tree_name}"


@cache_method(tree_cache_key)
def get_tree_by_name(tree_name: str) -> Optional[CombinedTree]:
    """Retrieve a `CombinedTree` representation of a tree by name.

    Returns `None` if no tree can be found.
    """
    latest_log = Log.objects.filter(tree=OuterRef("tree")).order_by("-created_at")

    # Create a `Tree` object annotated with `Log` values.
    tree = (
        Tree.objects.filter(tree=tree_name)
        .annotate(
            log_tags=Subquery(latest_log.values("tags")[:1]),
            log_status=Subquery(latest_log.values("status")[:1]),
            log_reason=Subquery(latest_log.values("reason")[:1]),
            log_id=Subquery(latest_log.values("id")[:1]),
        )
        .first()
    )

    if not tree:
        return None

    return CombinedTree(
        tree=tree.tree,
        message_of_the_day=tree.message_of_the_day,
        tags=tree.log_tags or [],
        # Force to a `TreeStatus` since `log_status` is just a `str`.
        status=TreeStatus(tree.log_status or tree.status),
        reason=tree.log_reason or tree.reason,
        category=tree.category,
        log_id=tree.log_id,
        instance=tree,
    )


def remove_tree_by_name(tree_name: str):
    """Completely remove the tree with the specified name.

    Note: this function commits the session.
    """
    tree = Tree.objects.filter(tree=tree_name).first()
    if not tree:
        raise NotFoundProblemException(
            detail=f"No tree {tree_name} found.",
            title="The tree does not exist.",
        )
    tree.delete()

    StatusChangeTree.objects.filter(tree=tree_name).delete()

    cache.delete(tree_cache_key(tree_name))


def update_tree_log(
    id: int, tags: Optional[list[str]] = None, reason: Optional[str] = None
):
    """Update the log with the given id with new `tags` and/or `reason`."""
    if tags is None and reason is None:
        return

    try:
        log = Log.objects.get(id=id)
    except Log.DoesNotExist as exc:
        raise NotFoundProblemException(
            title=f"No tree log for id {id} found.",
            detail=f"The tree log does not exist for id {id}.",
        ) from exc

    if tags is not None:
        log.tags = tags
    if reason is not None:
        log.reason = reason

    log.save()


def get_combined_trees(trees: Optional[list[str]] = None) -> list[CombinedTree]:
    """Return a `CombinedTree` representation of trees.

    If `trees` is set, return the `CombinedTree` for those trees, otherwise
    return all known trees.
    """
    latest_log = Log.objects.filter(tree=OuterRef("tree")).order_by("-created_at")

    qs = Tree.objects.annotate(
        log_tags=Subquery(latest_log.values("tags")[:1]),
        log_status=Subquery(latest_log.values("status")[:1]),
        log_reason=Subquery(latest_log.values("reason")[:1]),
        log_id=Subquery(latest_log.values("id")[:1]),
    )

    if trees:
        qs = qs.filter(tree__in=trees)

    return [
        get_combined_tree(
            tree, tree.log_tags, tree.log_status, tree.log_reason, tree.log_id
        )
        for tree in qs
    ]


def apply_tree_update_to_model(
    tree: Tree,
    user_id: str,
    status: Optional[str] = None,
    reason: Optional[str] = None,
    tags: Optional[list[str]] = None,
    message_of_the_day: Optional[str] = None,
):
    """Update the given tree's status."""
    tags = tags or []

    if status is not None:
        tree.status = TreeStatus(status)

    if reason is not None:
        tree.reason = reason

    if message_of_the_day is not None:
        tree.message_of_the_day = message_of_the_day

    tree.save()

    if status or reason:
        Log.objects.create(
            tree=tree,
            changed_by=user_id,
            status=TreeStatus(status) if status else tree.status,
            reason=reason or tree.reason,
            tags=tags,
        )

    cache.delete(tree_cache_key(tree.tree))


@treestatus_api.get(
    "/stack", response={200: Result[list[StackEntry]], codes_4xx: ProblemDetail}
)
@result_object_wrap
def api_get_stack(request: WSGIRequest) -> list[dict]:
    """Handler for `GET /stack`."""
    return StatusChange.get_stack()


def apply_status_change_update(
    id: int, tags: list[str] | None = None, reason: str | None = None
):
    """Update the tags and reason for a StatusChange and update associated logs."""
    change = StatusChange.objects.get(id=id)
    if not change:
        raise NotFoundProblemException(
            title=f"No stack {id} found.",
            detail="The change stack does not exist.",
        )

    for tree in change.trees.all():
        last_state = load_last_state(tree.last_state)
        last_state["current_tags"] = tags
        last_state["current_reason"] = reason

        update_tree_log(
            last_state["current_log_id"],
            tags,
            reason,
        )
        tree.last_state = last_state
        tree.save()

    change.reason = reason
    change.save()


def revert_status_change(id: int, user_id: str, revert: bool = False):
    """Revert the status change with the given ID.

    If `revert` is passed, also revert the updated trees statuses to their
    previous values.
    """
    try:
        status_change = StatusChange.objects.get(id=id)
    except StatusChange.DoesNotExist as exc:
        raise NotFoundProblemException(
            title=f"No change {id} found.",
            detail="The change could not be found.",
        ) from exc

    if revert:
        for changed_tree in status_change.trees.all():
            last_state = load_last_state(changed_tree.last_state)
            apply_tree_update_to_model(
                tree=changed_tree.tree,
                user_id=user_id,
                status=last_state["status"],
                reason=last_state["reason"],
                tags=last_state.get("tags", []),
            )

    status_change.delete()


@treestatus_api.get("/trees", response={200: Result[dict[str, TreeData]]})
@result_object_wrap
def api_get_trees(request: WSGIRequest) -> dict:
    """Handler for `GET /trees`."""
    return {tree.tree: tree.to_dict() for tree in get_combined_trees()}


def apply_tree_updates(
    user_id: str,
    trees: list[str],
    status: Optional[TreeStatus] = None,
    reason: Optional[str] = None,
    tags: Optional[list[str]] = None,
    remember: bool = False,
    message_of_the_day: Optional[str] = None,
) -> list[dict]:
    """Update a list of trees and optionally remember the change in a stack."""
    combined_trees = get_combined_trees(trees)

    if len(trees) != len(combined_trees):
        trees_diff = set(trees) - {tree.tree for tree in combined_trees}
        missing_trees = ", ".join(trees_diff)
        raise NotFoundProblemException(
            detail="Could not fetch all the requested trees.",
            title=f"Could not fetch the following trees: {missing_trees}",
        )

    if not tags and status == TreeStatus.CLOSED:
        raise BadRequestProblemException(
            detail="Tags are required when closing a tree.",
            title="Tags are required when closing a tree.",
        )

    if remember is True and any(field is None for field in (status, reason, tags)):
        raise BadRequestProblemException(
            title="Must specify status, reason and tags to remember the change.",
            detail="Must specify status, reason and tags to remember the change.",
        )

    old_trees = {}

    for tree in combined_trees:
        old_trees[tree.tree] = {
            "status": TreeStatus(tree.status),
            "reason": tree.reason,
            "tags": tree.tags,
            "log_id": tree.log_id,
        }

        apply_tree_update_to_model(
            tree.instance,
            user_id=user_id,
            status=status.value if status else None,
            reason=reason,
            message_of_the_day=message_of_the_day,
            tags=tags,
        )

    if remember:
        status_change = StatusChange.objects.create(
            changed_by=user_id,
            reason=reason or "",
            status=status or TreeStatus.OPEN,
        )

        new_trees = get_combined_trees([tree.tree for tree in combined_trees])
        for tree in new_trees:
            StatusChangeTree.objects.create(
                stack=status_change,
                tree=tree.instance,
                last_state=serialize_last_state(old_trees[tree.tree], tree),
            )

    return [
        {
            "tree": tree.tree,
            "status": status.value if status else tree.status,
            "reason": reason,
            "message_of_the_day": message_of_the_day,
        }
        for tree in combined_trees
    ]


@treestatus_api.get("/trees/{tree}", response={200: Result[TreeData]})
@result_object_wrap
def api_get_tree(request: WSGIRequest, tree: str) -> dict:
    """Handler for `GET /trees/{tree}`."""
    result = get_tree_by_name(tree)
    if result is None:
        raise NotFoundProblemException(
            detail=f"No tree {tree} found.",
            title="The tree does not exist.",
        )
    return result.to_dict()


def create_new_tree(
    user_id: str,
    tree: str,
    status: TreeStatus = TreeStatus.OPEN,
    reason: str = "Initial tree creation",
    message_of_the_day: str = "",
    category: TreeCategory = TreeCategory.OTHER,
) -> Tree:
    """Create a new `Tree` with the given fields."""
    try:
        new_tree = Tree.objects.create(
            tree=tree,
            status=status,
            reason=reason,
            message_of_the_day=message_of_the_day,
            category=category,
        )
    except IntegrityError as exc:
        raise BadRequestProblemException(
            title="Tree already exists.",
            detail=f"Tree {tree} already exists.",
        ) from exc

    # Create an initial log entry for the tree.
    Log.objects.create(
        tree=new_tree,
        changed_by=user_id,
        status=new_tree.status,
        reason=reason,
        tags=[],
    )

    return new_tree


def apply_log_and_stack_update(
    log_id: int, tags: list[str] | None = None, reason: str | None = None
):
    """Update the details of a log entry."""
    if tags is None and reason is None:
        return

    # Update the log table.
    update_tree_log(log_id, tags, reason)

    for change in StatusChange.objects.prefetch_related("trees"):
        for tree in change.trees.all():
            last_state = load_last_state(tree.last_state)
            if last_state["current_log_id"] != log_id:
                continue

            if reason:
                last_state["current_reason"] = reason
            if tags:
                last_state["current_tags"] = tags

            tree.last_state = last_state
            tree.save()


def get_tree_logs_by_name(tree_name: str, limit_logs: bool = True) -> list[dict]:
    """Return a list of Log entries as dicts.

    If `limit_logs` is `True`, limit the number of returned logs to the log limit.
    """
    # Verify the tree exists first.
    tree = Tree.objects.filter(tree=tree_name).first()
    if not tree:
        raise NotFoundProblemException(
            title=f"No tree {tree_name} found.",
            detail=f"Could not find the requested tree {tree_name}.",
        )

    query = Log.objects.filter(tree=tree_name).order_by("-created_at")
    if limit_logs:
        query = query[:TREE_SUMMARY_LOG_LIMIT]

    return [log.to_dict() for log in query]


@treestatus_api.get(
    "/trees/{tree}/logs_all",
    response={200: Result[list[LogEntry]], codes_4xx: ProblemDetail},
)
@result_object_wrap
def api_get_logs_all(request: WSGIRequest, tree: str) -> list[dict]:
    """Handler for `GET /trees/{tree}/logs_all`."""
    return get_tree_logs_by_name(tree, limit_logs=False)


@treestatus_api.get(
    "/trees/{tree}/logs",
    response={200: Result[list[LogEntry]], codes_4xx: ProblemDetail},
)
@result_object_wrap
def api_get_logs(request: WSGIRequest, tree: str) -> list[dict]:
    """Handler for `GET /trees/{tree}/logs`."""
    return get_tree_logs_by_name(tree, limit_logs=True)


@treestatus_api.get(
    "/trees2", response={200: Result[list[TreeData]], codes_4xx: ProblemDetail}
)
@result_object_wrap
def api_get_trees2(request: WSGIRequest) -> list[dict]:
    """Handler for `GET /trees2`."""
    return [tree.to_dict() for tree in get_combined_trees()]
