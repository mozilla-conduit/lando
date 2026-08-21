import functools
from datetime import datetime
from typing import (
    Callable,
    Generic,
    Optional,
    TypeVar,
)

from django.core.handlers.wsgi import WSGIRequest
from ninja import NinjaAPI, Schema
from ninja.responses import codes_4xx

from lando.treestatus.models import (
    StatusChange,
    TreeStatus,
)
from lando.treestatus.utils import (
    get_combined_trees,
    get_tree_by_name,
    get_tree_logs_by_name,
)
from lando.utils.exceptions import (
    NotFoundProblemException,
    ProblemDetail,
    ProblemException,
    problem_exception_handler,
)

treestatus_api = NinjaAPI(auth=None, urls_namespace="treestatus-api")
treestatus_api.exception_handler(ProblemException)(problem_exception_handler)


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


@treestatus_api.get(
    "/stack", response={200: Result[list[StackEntry]], codes_4xx: ProblemDetail}
)
@result_object_wrap
def api_get_stack(request: WSGIRequest) -> list[dict]:
    """Handler for `GET /stack`."""
    return StatusChange.get_stack()


@treestatus_api.get("/trees", response={200: Result[dict[str, TreeData]]})
@result_object_wrap
def api_get_trees(request: WSGIRequest, include_inactive: bool = False) -> dict:
    """Handler for `GET /trees`."""
    trees = get_combined_trees(is_active=None if include_inactive else True)
    return {tree.tree: tree.to_dict() for tree in trees}


@treestatus_api.get(
    "/trees2", response={200: Result[list[TreeData]], codes_4xx: ProblemDetail}
)
@result_object_wrap
def api_get_trees2(request: WSGIRequest, include_inactive: bool = False) -> list[dict]:
    """Handler for `GET /trees2`."""
    trees = get_combined_trees(is_active=None if include_inactive else True)
    return [tree.to_dict() for tree in trees]


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


@treestatus_api.get(
    "/trees/{tree}/logs",
    response={200: Result[list[LogEntry]], codes_4xx: ProblemDetail},
)
@result_object_wrap
def api_get_logs(request: WSGIRequest, tree: str) -> list[dict]:
    """Handler for `GET /trees/{tree}/logs`."""
    return get_tree_logs_by_name(tree, limit_logs=True)


@treestatus_api.get(
    "/trees/{tree}/logs_all",
    response={200: Result[list[LogEntry]], codes_4xx: ProblemDetail},
)
@result_object_wrap
def api_get_logs_all(request: WSGIRequest, tree: str) -> list[dict]:
    """Handler for `GET /trees/{tree}/logs_all`."""
    return get_tree_logs_by_name(tree, limit_logs=False)
