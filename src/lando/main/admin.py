from datetime import datetime

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
        "requester_email",
        "duration_seconds",
    )
    list_filter = ["target_repo__name", "requester_email", "created_at"]
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
    readonly_fields = [
        "attempts",
        "duration_seconds",
        "error",
        "formatted_replacements",
        "landed_commit_id",
    ]


class RevisionAdmin(admin.ModelAdmin):
    model = Revision
    list_display = (
        "revision",
        "desc",
        "datetime",
        "author",
    )

    def revision(self, instance: Revision) -> str:
        return f"D{instance.revision_id}"

    def datetime(self, instance: Revision) -> datetime | None:
        ts = instance.patch_data.get("timestamp")
        if not isinstance(ts, int):
            return None
        return datetime.fromtimestamp(ts)

    def author(self, instance: Revision) -> str:
        author_name = instance.patch_data.get("author_name")
        author_email = instance.patch_data.get("author_email")

        author_list = []

        if author_name:
            author_list.append(author_name)

        if author_email:
            author_email = f"<{author_email}>"
            author_list.append(author_email)

        if not author_list:
            return "-"

        return " ".join(author_list)

    def desc(self, instance: Revision) -> str:
        return (instance.patch_data.get("commit_message") or "-").splitlines()[0]


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
admin.site.register(Revision, RevisionAdmin)
admin.site.register(Worker, admin.ModelAdmin)
admin.site.register(ConfigurationVariable, ConfigurationVariableAdmin)
