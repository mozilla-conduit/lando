from datetime import datetime
from typing import Callable, Self

from django.contrib import admin
from django.utils.translation import gettext_lazy

from lando.main.models import (
    CommitMap,
    ConfigurationVariable,
    LandingJob,
    MultiTrainUpliftRequest,
    Repo,
    Revision,
    RevisionLandingJob,
    RevisionUpliftJob,
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
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


class RevisionUpliftJobInline(admin.TabularInline):
    model = RevisionUpliftJob
    fields = ("index", "revision")
    readonly_fields = ("index", "revision")
    extra = 0
    can_delete = False
    ordering = ("index",)
    raw_id_fields = ("revision",)


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
    list_display = (
        "id",
        "revisions",
        "status",
        "target_repo__name",
        "created_at",
        "requester_email",
        "duration_seconds",
    )
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
    search_fields = JobAdmin.search_fields + (
        "unsorted_revisions__revision_id",
        "requester_email",
    )

    def revisions(self, instance: LandingJob) -> str:
        """Return a summary of revisions present in a LandingJob

        The summary is the str of the last revision, and a count of all the other
        revisions present in the Landing Job.
        """
        last_revision = instance.unsorted_revisions.order_by("-id").last()
        nrevisions = instance.unsorted_revisions.count()
        summary = "(no revision)"
        if last_revision:
            summary = str(last_revision)
            if (nrevisions := nrevisions - 1) > 0:
                summary = (
                    f"{summary} and {nrevisions} other{'s' if nrevisions > 1 else ''}"
                )

        return summary


class UpliftJobAdmin(JobAdmin):
    model = UpliftJob
    list_display = (
        "id",
        "revisions_summary",
        "status",
        "target_repo__name",
        "multi_request_user",
        "created_at",
        "requester_email",
        "duration_seconds",
    )
    list_filter = ("status", "target_repo__name", "multi_request__user")
    inlines = (RevisionUpliftJobInline,)
    fields = (
        "status",
        "attempts",
        "duration_seconds",
        "error",
        "priority",
        "requester_email",
        "multi_request",
        "target_repo",
        "created_revision_ids",
        "landed_commit_id",
        "created_at",
        "updated_at",
    )
    readonly_fields = JobAdmin.readonly_fields + (
        "multi_request",
        "created_revision_ids",
        "created_at",
        "updated_at",
    )
    search_fields = JobAdmin.search_fields + (
        "multi_request__user__email",
        "unsorted_revisions__revision_id",
        "created_revision_ids",
    )

    @admin.display(description="Requester", ordering="multi_request__user__email")
    def multi_request_user(self, instance: UpliftJob) -> str:
        """Return the email address of the uplift request submitter."""
        return instance.multi_request.user.email

    @admin.display(description="Revisions")
    def revisions_summary(self, instance: UpliftJob) -> str:
        """Return a concise description of revisions processed by the job."""
        revisions = list(instance.revisions)
        if not revisions:
            return "(no revision)"
        first = revisions[0]
        remaining = len(revisions) - 1
        summary = str(first)
        if remaining > 0:
            summary = f"{summary} (+{remaining} more)"
        return summary


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
        idstr = f"{instance.id}"

        if instance.is_phabricator_revision:
            return f"D{instance.revision_id} ({idstr})"

        return idstr

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


class UpliftAssessmentAdmin(admin.ModelAdmin):
    model = UpliftAssessment
    list_display = (
        "id",
        "user_email",
        "risk_associated_with_patch",
        "covered_by_testing",
        "created_at",
        "updated_at",
    )
    list_filter = ("risk_associated_with_patch", "covered_by_testing", "created_at")
    search_fields = (
        "user__email",
        "user_impact",
        "risk_level_explanation",
        "string_changes",
    )
    readonly_fields = ("user", "created_at", "updated_at")

    @admin.display(description="Requester", ordering="user__email")
    def user_email(self, instance: UpliftAssessment) -> str:
        return instance.user.email


class UpliftRevisionAdmin(admin.ModelAdmin):
    model = UpliftRevision
    list_display = (
        "revision_identifier",
        "assessment_user",
        "created_at",
        "updated_at",
    )
    search_fields = ("revision_id", "assessment__user__email")
    readonly_fields = ("assessment", "created_at", "updated_at")

    @admin.display(description="Revision", ordering="revision_id")
    def revision_identifier(self, instance: UpliftRevision) -> str:
        return f"D{instance.revision_id}" if instance.revision_id else "-"

    @admin.display(
        description="Assessment requester", ordering="assessment__user__email"
    )
    def assessment_user(self, instance: UpliftRevision) -> str:
        return instance.assessment.user.email


class UpliftJobInline(admin.TabularInline):
    model = UpliftJob
    fields = ("id", "status", "target_repo", "created_revision_summary", "created_at")
    readonly_fields = (
        "id",
        "status",
        "target_repo",
        "created_revision_summary",
        "created_at",
    )
    extra = 0
    can_delete = False
    show_change_link = True

    @admin.display(description="Created revisions")
    def created_revision_summary(self, instance: UpliftJob) -> str:
        if not instance.created_revision_ids:
            return "-"
        revisions = [f"D{rev}" for rev in instance.created_revision_ids]
        preview = ", ".join(revisions[:3])
        remaining = len(revisions) - 3
        if remaining > 0:
            preview = f"{preview} (+{remaining} more)"
        return preview


class MultiTrainUpliftRequestAdmin(admin.ModelAdmin):
    model = MultiTrainUpliftRequest
    list_display = (
        "id",
        "user_email",
        "requested_revision_summary",
        "job_count",
        "created_at",
        "updated_at",
    )
    list_filter = ("created_at",)
    search_fields = ("user__email", "requested_revision_ids")
    readonly_fields = ("created_at", "updated_at")
    inlines = (UpliftJobInline,)

    @admin.display(description="Requester", ordering="user__email")
    def user_email(self, instance: MultiTrainUpliftRequest) -> str:
        return instance.user.email

    @admin.display(description="Requested revisions")
    def requested_revision_summary(self, instance: MultiTrainUpliftRequest) -> str:
        revisions = [f"D{rev}" for rev in instance.requested_revision_ids or []]
        if not revisions:
            return "-"
        preview = ", ".join(revisions[:3])
        remaining = len(revisions) - 3
        if remaining > 0:
            preview = f"{preview} (+{remaining} more)"
        return preview

    @admin.display(description="Jobs")
    def job_count(self, instance: MultiTrainUpliftRequest) -> int:
        return instance.uplift_jobs.count()


admin.site.register(Repo, RepoAdmin)
admin.site.register(LandingJob, LandingJobAdmin)
admin.site.register(UpliftJob, UpliftJobAdmin)
admin.site.register(Revision, RevisionAdmin)
admin.site.register(Worker, WorkerAdmin)
admin.site.register(CommitMap, CommitMapAdmin)
admin.site.register(ConfigurationVariable, ConfigurationVariableAdmin)
admin.site.register(UpliftAssessment, UpliftAssessmentAdmin)
admin.site.register(UpliftRevision, UpliftRevisionAdmin)
admin.site.register(MultiTrainUpliftRequest, MultiTrainUpliftRequestAdmin)
