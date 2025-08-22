from django.contrib import admin

from lando.main.admin import ReadOnlyInline
from lando.pushlog.models import (
    Commit,
    File,
    Push,
    Tag,
)


class PushLogAdmin(admin.ModelAdmin):
    """A base ModelAdmin class for PushLog-related admin parameters."""

    def has_add_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        """Forbid addition of any pushlog object from the admin interface."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        """Forbid change of any pushlog object from the admin interface."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        """Forbid deletion of any pushlog object from the admin interface."""
        return False


class PushCommitInline(ReadOnlyInline):
    # https://docs.djangoproject.com/en/5.0/ref/contrib/admin/#working-with-many-to-many-models
    model = Push.commits.through

    # Used by ReadOnlyInline._field_getter_factory
    _target_object = "commit"

    readonly_fields = ("hash_short", "desc", "author")

    def hash_short(self, instance: Commit) -> str:
        return instance.commit.hash[:8]

    def desc(self, instance: Commit) -> str:
        return instance.commit.desc.splitlines()[0]


class PushTagInline(ReadOnlyInline):
    model = Push.tags.through

    # Used by ReadOnlyInline._field_getter_factory
    _target_object = "tag"

    readonly_fields = ("name", "commit")


class PushAdmin(PushLogAdmin):
    model = Push
    readonly_fields = (
        "push_id",
        "notified",
        "repo",
        "repo_url",
        "branch",
        "datetime",
        "user",
    )
    inlines = (PushCommitInline, PushTagInline)
    exclude = ("commits", "tags")
    list_display = (
        "push_id",
        "notified",
        "repo__name",
        "branch",
        "commit_summary",
        "tag_summary",
        "datetime",
        "user",
    )
    list_filter = ("repo", "branch", "datetime")
    search_fields = ("user", "commits__hash", "tags__name")

    def commit_summary(self, instance: Push) -> str:
        """Return a summary of commits present in a Push.

        The summary is the hash of the last commit, and a count of all the other
        commits present in the Push.
        """
        last_commit = instance.commits.order_by("-id").last()
        ncommits = instance.commits.count()
        summary = "(no commit)"
        if last_commit:
            summary = last_commit.hash[:8]
            if (ncommits := ncommits - 1) > 0:
                summary = f"{summary} and {ncommits} commit{'s' if ncommits else ''}"

        return summary

    def tag_summary(self, instance: Push) -> str:
        """Return a summary of tags present in a Push.

        The summary is the hash of the last tag, and a count of all the other
        tags present in the Push.
        """
        last_tag = instance.tags.order_by("-id").last()
        ntags = instance.tags.count()
        summary = "(no tag)"
        if last_tag:
            summary = f"{last_tag.name} to {last_tag.commit.hash}"
            if (ntags := ntags - 1) > 0:
                summary = f"{summary} and {ntags} tag{'s' if ntags else ''}"

        return summary


class CommitPushInline(ReadOnlyInline):
    model = Push.commits.through
    _target_object = "push"

    readonly_fields = (
        "push_id",
        "repo",
        "branch",
        "datetime",
        "user",
    )


class CommitAdmin(PushLogAdmin):
    model = Commit
    readonly_fields = (
        "repo",
        "hash",
        "parents",
        "author",
        "datetime",
        "desc",
        "_files",
        "_parents",
    )
    search_fields = ("author", "hash", "desc")

    list_display = ("hash_short", "repo__name", "desc_first", "datetime", "author")
    list_filter = ("repo", "datetime")
    inlines = (CommitPushInline,)

    def hash_short(self, instance: Commit) -> str:
        return instance.hash[:8]

    def desc_first(self, instance: Commit) -> str:
        return instance.desc.splitlines()[0]


class FileAdmin(PushLogAdmin):
    readonly_fields = (
        "repo",
        "name",
    )
    search_fields = ("name",)
    list_display = ("name", "repo__name")
    list_filter = ("repo",)


class TagPushInline(CommitPushInline):
    model = Push.tags.through
    _target_object = "push"


class TagAdmin(PushLogAdmin):
    readonly_fields = (
        "repo",
        "name",
        "commit",
    )
    search_fields = ("name", "commit__hash")
    list_display = ("name", "commit", "repo__name")
    list_filter = ("repo",)
    inlines = (TagPushInline,)


admin.site.register(Push, PushAdmin)
admin.site.register(Commit, CommitAdmin)
admin.site.register(File, FileAdmin)
admin.site.register(Tag, TagAdmin)
