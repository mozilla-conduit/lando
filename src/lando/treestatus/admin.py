from django.contrib import admin
from django.urls import reverse

from lando.main.admin import ReadOnlyInline, ReadOnlyModelAdmin
from lando.treestatus.models import (
    Log,
    StatusChange,
    StatusChangeTree,
    Tree,
)


def summarize(text: str, length: int = 80) -> str:
    """Return the first line of `text`, truncated to `length` characters."""
    if not text:
        return "-"

    first_line = text.splitlines()[0]
    if len(first_line) <= length:
        return first_line

    return f"{first_line[:length]}..."


class TreeAdmin(admin.ModelAdmin):
    model = Tree
    list_display = (
        "tree",
        "status",
        "category",
        "reason_summary",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "category")
    search_fields = ("tree", "reason", "message_of_the_day")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("tree",)

    def view_on_site(self, instance: Tree) -> str:
        url = reverse("treestatus-tree-logs", kwargs={"tree": instance.tree})
        return url

    @admin.display(description="Reason", ordering="reason")
    def reason_summary(self, instance: Tree) -> str:
        """Return a shortened version of the reason the tree is in its current state."""
        return summarize(instance.reason)


class LogAdmin(ReadOnlyModelAdmin):
    """Admin for the log of status changes applied to a single tree."""

    model = Log
    list_display = (
        "id",
        "tree",
        "status",
        "reason_summary",
        "tags",
        "changed_by",
        "created_at",
    )
    list_filter = ("status", "tree", "created_at")
    search_fields = ("tree__tree", "changed_by", "reason")
    readonly_fields = (
        "tree",
        "status",
        "reason",
        "tags",
        "changed_by",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)

    @admin.display(description="Reason", ordering="reason")
    def reason_summary(self, instance: Log) -> str:
        """Return a shortened version of the reason for the status change."""
        return summarize(instance.reason)


class StatusChangeTreeInline(ReadOnlyInline):
    """Show the trees affected by a `StatusChange`, along with their prior state."""

    model = StatusChangeTree
    fields = ("tree", "last_state")
    readonly_fields = fields
    show_change_link = True


class StatusChangeAdmin(ReadOnlyModelAdmin):
    """Admin for entries of the stack of recent status changes."""

    model = StatusChange
    list_display = (
        "id",
        "status",
        "tree_summary",
        "reason_summary",
        "changed_by",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("changed_by", "reason", "trees__tree__tree")
    readonly_fields = (
        "status",
        "reason",
        "changed_by",
        "created_at",
        "updated_at",
    )
    inlines = (StatusChangeTreeInline,)
    ordering = ("-created_at",)

    @admin.display(description="Trees")
    def tree_summary(self, instance: StatusChange) -> str:
        """Return a summary of the trees affected by the status change."""
        trees = list(instance.trees.values_list("tree__tree", flat=True))
        if not trees:
            return "(no tree)"

        summary = ", ".join(trees[:3])
        if (remaining := len(trees) - 3) > 0:
            summary = f"{summary} (+{remaining} more)"

        return summary

    @admin.display(description="Reason", ordering="reason")
    def reason_summary(self, instance: StatusChange) -> str:
        """Return a shortened version of the reason for the status change."""
        return summarize(instance.reason)


class StatusChangeTreeAdmin(ReadOnlyModelAdmin):
    """Admin for the state a tree was in before a `StatusChange` was applied."""

    model = StatusChangeTree
    list_display = ("id", "tree", "stack", "created_at")
    list_filter = ("tree", "created_at")
    search_fields = ("tree__tree", "stack__changed_by")
    readonly_fields = ("stack", "tree", "last_state", "created_at", "updated_at")
    ordering = ("-created_at",)


admin.site.register(Tree, TreeAdmin)
admin.site.register(Log, LogAdmin)
admin.site.register(StatusChange, StatusChangeAdmin)
admin.site.register(StatusChangeTree, StatusChangeTreeAdmin)
