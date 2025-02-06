from django.contrib import admin

from lando.pushlog.models import (
    Commit,
    File,
    Push,
    Tag,
)


class PushLogAdmin(admin.ModelAdmin):
    """A base ModelAdmin class for PushLog-related admin parameters."""

    def has_add_permission(self, request, obj=None):
        """Fordib addition of any pushlog object from the admin interface."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Fordib deletion of any pushlog object from the admin interface."""
        return False


class PushAdmin(PushLogAdmin):
    readonly_fields = (
        "push_id",
        "repo",
        "repo_url",
        "branch",
        "datetime",
        "user",
        "commits",
    )


class CommitAdmin(PushLogAdmin):
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


class FileAdmin(PushLogAdmin):
    readonly_fields = (
        "repo",
        "name",
    )


class TagAdmin(PushLogAdmin):
    readonly_fields = (
        "repo",
        "name",
        "commit",
    )


admin.site.register(Push, PushAdmin)
admin.site.register(Commit, CommitAdmin)
admin.site.register(File, FileAdmin)
admin.site.register(Tag, TagAdmin)
