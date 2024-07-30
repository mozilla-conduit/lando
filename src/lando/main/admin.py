from django.contrib import admin
from django.utils.translation import gettext_lazy

from lando.main.models.access_group import AccessGroup
from lando.main.models.landing_job import LandingJob
from lando.main.models.repo import Repo, Worker
from lando.main.models.revision import Revision, RevisionLandingJob

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


class AccessGroupAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "permission",
        "active_group",
        "expired_group",
        "membership_group",
    )
    ordering = ("display_name",)


admin.site.register(AccessGroup, AccessGroupAdmin)
admin.site.register(LandingJob, LandingJobAdmin)
admin.site.register(Revision, admin.ModelAdmin)
admin.site.register(Repo, admin.ModelAdmin)
admin.site.register(Worker, admin.ModelAdmin)
