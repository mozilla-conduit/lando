from django.contrib import admin
from django.utils.translation import gettext_lazy

from lando.main.models.base import Repo, Worker
from lando.main.models.landing_job import LandingJob
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


admin.site.register(LandingJob, LandingJobAdmin)
admin.site.register(Revision, admin.ModelAdmin)
admin.site.register(Repo, admin.ModelAdmin)
admin.site.register(Worker, admin.ModelAdmin)
