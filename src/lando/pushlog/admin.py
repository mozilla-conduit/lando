from typing import Callable, Self

from django.contrib import admin

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


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = False

    def _field_getter_factory(self, f: str) -> Callable:
        """Programatically add getters for all readonly fields which don't have one.

        [0] https://forum.djangoproject.com/t/show-all-the-fields-in-inline-of-the-many-to-many-model-instead-of-a-simple-dropdown/28062/7
        """

        def getter(self: Self):
            return getattr(getattr(self, self._target_object), f)

        getter.__name__ = f

        return getter

    def __init__(self, *args, **kwargs):
        for f in self.readonly_fields:
            if not hasattr(self, f):
                setattr(self, f, self._field_getter_factory(f))
        super().__init__(*args, **kwargs)


class PushCommitInline(ReadOnlyInline):
    # https://docs.djangoproject.com/en/5.0/ref/contrib/admin/#working-with-many-to-many-models
    model = Push.commits.through

    # Used by ReadOnlyInline._field_getter_factory
    _target_object = "commit"

    readonly_fields = ["hash_short", "desc", "author"]

    def hash_short(self, instance: Commit) -> str:
        return instance.commit.hash[:8]

    def desc(self, instance: Commit) -> str:
        return instance.commit.desc.splitlines()[0]


class PushTagInline(ReadOnlyInline):
    model = Push.tags.through

    # Used by ReadOnlyInline._field_getter_factory
    _target_object = "tag"

    readonly_fields = ["name", "commit"]


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
    inlines = [PushCommitInline, PushTagInline]
    exclude = ["commits", "tags"]
    list_display = [
        "push_id",
        "notified",
        "repo__name",
        "branch",
        "commit_summary",
        "tag_summary",
        "datetime",
        "user",
    ]
    list_filter = ["repo", "branch", "user", "datetime"]

    def commit_summary(self, instance: Push) -> str:
        last_commit = instance.commits.order_by("-id").last()
        ncommits = instance.commits.count()
        summary = "(no commit)"
        if last_commit:
            summary = last_commit.hash[:8]
            if (ncommits := ncommits - 1) > 0:
                summary = f"{summary} and {ncommits} commit{'s' if ncommits else ''}"

        return summary

    def tag_summary(self, instance: Push) -> str:
        last_tag = instance.tags.order_by("-id").last()
        ntags = instance.tags.count()
        summary = "(no tag)"
        if last_tag:
            summary = f"{last_tag.name} to {last_tag.commit.hash}"
            if (ntags := ntags - 1) > 0:
                summary = f"{summary} and {ntags} tag{'s' if ntags else ''}"

        return summary


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
    list_display = ["hash_short", "repo__name", "desc_first", "datetime", "author"]
    list_filter = ["repo", "author", "datetime"]

    def hash_short(self, instance: Commit) -> str:
        return instance.hash[:8]

    def desc_first(self, instance: Commit) -> str:
        return instance.desc.splitlines()[0]


class FileAdmin(PushLogAdmin):
    readonly_fields = (
        "repo",
        "name",
    )
    list_display = ["name", "repo__name"]
    list_filter = ["repo"]


class TagAdmin(PushLogAdmin):
    readonly_fields = (
        "repo",
        "name",
        "commit",
    )
    list_display = ["name", "commit", "repo__name"]
    list_filter = ["repo"]


admin.site.register(Push, PushAdmin)
admin.site.register(Commit, CommitAdmin)
admin.site.register(File, FileAdmin)
admin.site.register(Tag, TagAdmin)
