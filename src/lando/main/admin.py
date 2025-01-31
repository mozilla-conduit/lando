from django.contrib import admin
from django.utils.translation import gettext_lazy

from lando.main.models import (
    ConfigurationVariable,
    LandingJob,
    Repo,
    Revision,
    RevisionLandingJob,
    Worker,
)
from lando.pushlog.models import (
    Commit,
    File,
    Push,
    Tag,
)

admin.site.site_title = gettext_lazy("Lando Admin")
admin.site.site_header = gettext_lazy("Lando Administration")
admin.site.index_title = gettext_lazy("Lando administration")


class RevisionLandingJobInline(admin.TabularInline):
    model = RevisionLandingJob
    fields = ("revision",)


class LandingJobAdmin(admin.ModelAdmin):
    model = LandingJob
    inlines = [RevisionLandingJobInline]
    fields = (
        "status",
        "attempts",
        "duration_seconds",
        "error",
        "landed_commit_id",
        "priority",
        "repository_name",
        "repository_url",
        "requester_email",
        "target_commit_hash",
        "target_repo",
    )


admin.site.register(LandingJob, LandingJobAdmin)
admin.site.register(Revision, admin.ModelAdmin)
admin.site.register(Repo, admin.ModelAdmin)
admin.site.register(Worker, admin.ModelAdmin)
admin.site.register(ConfigurationVariable, admin.ModelAdmin)


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
