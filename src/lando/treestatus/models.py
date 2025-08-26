import copy
from dataclasses import (
    asdict,
    dataclass,
)
from enum import Enum
from typing import (
    Any,
    Optional,
)

from django.db import models

from lando.main.models import BaseModel


class TreeStatus(models.TextChoices):
    """Allowable statuses of a tree."""

    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    APPROVAL_REQUIRED = "approval required", "Approval required"

    def is_open(self) -> bool:
        """Return `True` if Lando should consider this status as open for landing.

        A repo is considered open for landing when the state is "open" or
        "approval required". For the "approval required" status Lando will enforce
        the appropriate Phabricator group review for approval (`release-managers`)
        and the hg hook will enforce `a=<reviewer>` is present in the commit message.
        """
        return self in {TreeStatus.OPEN, TreeStatus.APPROVAL_REQUIRED}


class TreeCategory(models.TextChoices):
    """Categories of the various trees.

    Note: the definition order is in order of importance for display in the UI.
    """

    DEVELOPMENT = "development", "Development"
    RELEASE_STABILIZATION = "release_stabilization", "Release Stabilization"
    TRY = "try", "Try"
    COMM_REPOS = "comm_repos", "Comm Repos"
    OTHER = "other", "Other"

    @classmethod
    def sort_trees(cls, item: "CombinedTree") -> int:
        """Key function for sorting tree `dict`s according to category order."""
        return [choice.value for choice in list(cls)].index(item.category)


def get_default_tree() -> dict[str, Any]:
    return {
        "category": TreeCategory.OTHER,
        "reason": "New tree",
        "status": TreeStatus.CLOSED,
        "tags": [],
        "log_id": None,
    }


def load_last_state(last_state_orig: dict) -> dict:
    """Ensure that structure of last_state is backwards compatible."""
    last_state = copy.deepcopy(last_state_orig)
    default_tree = get_default_tree()

    for field in [
        "status",
        "reason",
        "tags",
        "log_id",
        "current_status",
        "current_reason",
        "current_tags",
        "current_log_id",
    ]:
        if field in last_state:
            continue
        if field.startswith("current_"):
            last_state[field] = default_tree[field[len("current_") :]]
        else:
            last_state[field] = default_tree[field]

    return last_state


class Tree(BaseModel):
    """A Tree that is managed via Treestatus."""

    tree = models.CharField(
        max_length=64, unique=True, db_index=True, null=False, blank=False
    )

    status = models.CharField(
        max_length=20,
        choices=TreeStatus,
        default=TreeStatus.OPEN,
        null=False,
        blank=False,
    )

    reason = models.TextField(default="", null=False, blank=True)

    message_of_the_day = models.TextField(default="", null=False, blank=True)

    category = models.CharField(
        max_length=32,
        choices=TreeCategory,
        default=TreeCategory.OTHER,
        null=False,
        blank=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert a `Tree` into a dict."""
        return {
            "tree": self.tree,
            "status": self.status,
            "reason": self.reason,
            "message_of_the_day": self.message_of_the_day,
            "category": self.category,
        }

    def __str__(self) -> str:
        return f"{self.tree} ({self.status})"


class Log(BaseModel):
    """A log of changes to a Tree."""

    tree = models.ForeignKey(
        Tree,
        to_field="tree",
        db_column="tree",
        on_delete=models.CASCADE,
        db_index=True,
    )

    changed_by = models.TextField(null=False, blank=False)

    status = models.CharField(
        max_length=20, choices=TreeStatus, null=False, blank=False
    )

    reason = models.TextField(null=False, blank=False)

    tags = models.JSONField(default=list, null=False, blank=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert a `Log` to a `dict`."""
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status,
            "tags": self.tags,
            "tree": self.tree.tree,
            "when": self.created_at.isoformat() if self.created_at else None,
            "who": self.changed_by,
        }

    def __str__(self) -> str:
        return f"Log #{self.id} for {self.tree} by {self.changed_by}"


class StatusChange(BaseModel):
    """A change of status which applies to trees."""

    changed_by = models.TextField(null=False, blank=False)

    reason = models.TextField(null=False, blank=False)

    status = models.CharField(
        max_length=20, choices=TreeStatus, null=False, blank=False
    )

    @classmethod
    def get_stack(cls) -> list[dict]:
        """Return the current stack of changes."""
        return [
            status_change.to_dict()
            for status_change in cls.objects.order_by("-created_at")
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert the `StatusChange` to a `dict` representation."""
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status,
            "trees": [tree.to_dict() for tree in self.trees.all()],
            "when": self.created_at.isoformat() if self.created_at else None,
            "who": self.changed_by,
        }

    def __str__(self) -> str:
        return f"StatusChange #{self.id} by {self.changed_by}"


class StatusChangeTree(BaseModel):
    """A tree (i.e., a 'stack') of status changes."""

    stack = models.ForeignKey(
        StatusChange, related_name="trees", on_delete=models.CASCADE, db_index=True
    )

    tree = models.ForeignKey(
        Tree,
        to_field="tree",
        db_column="tree",
        on_delete=models.CASCADE,
        db_index=True,
    )

    last_state = models.JSONField(null=False, blank=False)

    def to_dict(self) -> dict[str, Any]:
        """Convert the `StatusChangeTree` to a `dict`."""
        return {
            "id": self.id,
            "last_state": load_last_state(self.last_state),
            "tree": self.tree.tree,
        }

    def __str__(self) -> str:
        return f"StatusChangeTree #{self.id} for {self.tree}"


class ReasonCategory(models.TextChoices):
    """Allowable reasons for a Tree closure."""

    NO_CATEGORY = "", "No Category"
    JOB_BACKLOG = "backlog", "Job Backlog"
    CHECKIN_COMPILE_FAILURE = "checkin_compilation", "Check-in compilation failure"
    CHECKIN_TEST_FAILURE = "checkin_test", "Check-in test failure"
    PLANNED_CLOSURE = "planned", "Planned closure"
    MERGES = "merges", "Merges"
    WAITING_FOR_COVERAGE = "waiting_for_coverage", "Waiting for coverage"
    INFRASTRUCTURE_RELATED = "infra", "Infrastructure related"
    OTHER = "other", "Other"


@dataclass
class CombinedTree:
    """Combined view of a `Tree` with values from the most recent `Log`."""

    tree: str
    message_of_the_day: str
    tags: list[str]
    status: TreeStatus
    reason: str
    category: TreeCategory
    log_id: Optional[int]
    instance: Tree

    @property
    def reason_category(self) -> ReasonCategory:
        """Return the tags as a `ReasonCategory`."""
        try:
            return ReasonCategory(self.tags[0])
        except (IndexError, ValueError):
            return ReasonCategory.NO_CATEGORY

    def to_dict(self) -> dict:
        """Convert the `CombinedTree` to a `dict`."""
        return {
            field: (value.value if isinstance(value, Enum) else value)
            for field, value in asdict(self).items()
            if field != "instance"
        }
