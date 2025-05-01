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

admin.site.site_title = gettext_lazy("Lando Admin")
admin.site.site_header = gettext_lazy("Lando Administration")
admin.site.index_title = gettext_lazy("Lando administration")


class RevisionLandingJobInline(admin.TabularInline):
    model = RevisionLandingJob
    fields = ("revision",)


class LandingJobAdmin(admin.ModelAdmin):
    model = LandingJob
    inlines = [RevisionLandingJobInline]
    list_display = (
        "id",
        "status",
        "target_repo__name",
        "created_at",
        "duration_seconds",
    )
    fields = (
        "status",
        "attempts",
        "duration_seconds",
        "error",
        "formatted_replacements",
        "landed_commit_id",
        "priority",
        "repository_name",
        "repository_url",
        "requester_email",
        "target_commit_hash",
        "target_repo",
    )


class RepoAdmin(admin.ModelAdmin):
    model = Repo
    list_display = (
        "name",
        "scm_type",
        "system_path",
        "pull_path",
        "push_path",
        "required_permission",
        "short_name",
        "url",
    )

    readonly_fields = (
        "commit_flags",
        "system_path",
        "scm_type",
    )


class ConfigurationVariableAdmin(admin.ModelAdmin):
    model = ConfigurationVariable
    list_display = (
        "key",
        "value",
    )


admin.site.register(Repo, RepoAdmin)
admin.site.register(LandingJob, LandingJobAdmin)
admin.site.register(Revision, admin.ModelAdmin)
admin.site.register(Worker, admin.ModelAdmin)
admin.site.register(ConfigurationVariable, ConfigurationVariableAdmin)
