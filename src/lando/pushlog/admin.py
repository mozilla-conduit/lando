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
    list_display = ["push_id", "repo__name", "branch", "datetime", "user"]
    list_filter = ["repo", "branch", "user", "datetime"]


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
    list_display = ["hash", "repo__name", "datetime", "author"]
    list_filter = ["repo", "author", "datetime"]


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
