from datetime import datetime
from typing import Callable, Self

from django.contrib import admin
from django.utils.translation import gettext_lazy

from lando.main.models import (
    CommitMap,
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


class ReadOnlyInline(admin.TabularInline):
    """
    A Tabular Inline that supports a readonly_fields to disallow editing linked models.

    The `_target_object` *string* property needs to be set on child classes so fields are
    automatically discovered for the target model. This string should be the name of the
    attribute on the `model` class that contains the link.

    """

    extra = 0
    can_delete = False
    show_change_link = False

    @classmethod
    def _field_getter_factory(cls, f: str) -> Callable:
        """Programatically add getters for all readonly fields which don't have one.

        [0] https://forum.djangoproject.com/t/show-all-the-fields-in-inline-of-the-many-to-many-model-instead-of-a-simple-dropdown/28062/7
        """

        def getter(self: Self):
            return getattr(getattr(self, cls._target_object), f)

        getter.__name__ = f

        return getter

    def __init__(self, *args, **kwargs):
        for f in self.readonly_fields:
            if not hasattr(self, f):
                setattr(self, f, self._field_getter_factory(f))
        super().__init__(*args, **kwargs)


class RevisionLandingJobInline(admin.TabularInline):
    model = RevisionLandingJob
    fields = ("revision",)


class JobAdmin(admin.ModelAdmin):
    """A base admin class for jobs."""

    list_display = (
        "id",
        "status",
        "target_repo__name",
        "created_at",
        "requester_email",
        "duration_seconds",
    )
    list_filter = ("target_repo__name", "created_at")
    readonly_fields = (
        "attempts",
        "duration_seconds",
        "error",
        "landed_commit_id",
        "requester_email",
    )
    search_fields = ("requester_email", "landed_commit_id")


class LandingJobAdmin(JobAdmin):
    model = LandingJob
    inlines = (RevisionLandingJobInline,)
    fields = (
        "status",
        "attempts",
        "duration_seconds",
        "error",
        "formatted_replacements",
        "landed_commit_id",
        "priority",
        "requester_email",
        "target_commit_hash",
        "target_repo",
    )
    readonly_fields = JobAdmin.readonly_fields + ("formatted_replacements",)
    search_fields = JobAdmin.search_fields + ("requester_email",)


class RevisionAdmin(admin.ModelAdmin):
    model = Revision
    list_display = (
        "revision",
        "desc",
        "patch_timestamp",
        "author",
    )
    search_fields = ("revision_id",)

    def revision(self, instance: Revision) -> str:
        """Return a Phabricator-like revision identifier."""
        return f"D{instance.revision_id}"

    def patch_timestamp(self, instance: Revision) -> datetime | None:
        """Return a datetime based on the timestamp from the patch data."""
        ts = instance.patch_data.get("timestamp")
        if not isinstance(ts, int):
            return None
        return datetime.fromtimestamp(ts)

    def author(self, instance: Revision) -> str:
        """Return an author string based on information available in the patch data."""
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
        """Return the first line of the commit message in the patch data."""
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

    search_fields = ("pull_path", "push_path", "url")


class CommitMapAdmin(admin.ModelAdmin):
    model = CommitMap
    list_display = (
        "git_repo_name",
        "git_hash",
        "hg_hash",
    )
    list_filter = ("git_repo_name",)
    search_fields = (
        "git_hash",
        "hg_hash",
    )


class ConfigurationVariableAdmin(admin.ModelAdmin):
    model = ConfigurationVariable
    list_display = (
        "key",
        "value",
    )
    search_fields = (
        "key",
        "value",
    )


class WorkerAdmin(admin.ModelAdmin):
    model = Worker
    list_display = (
        "name",
        "type",
        "scm",
        "repo_count",
        "is_paused",
        "is_stopped",
    )
    search_fields = ("applicable_repos__name",)

    def repo_count(self, instance: Worker) -> int:
        """Return the count of repositories associated to the Worker."""
        return instance.applicable_repos.count()


admin.site.register(Repo, RepoAdmin)
admin.site.register(LandingJob, LandingJobAdmin)
admin.site.register(Revision, RevisionAdmin)
admin.site.register(Worker, WorkerAdmin)
admin.site.register(CommitMap, CommitMapAdmin)
admin.site.register(ConfigurationVariable, ConfigurationVariableAdmin)
