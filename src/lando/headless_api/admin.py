from django.contrib import admin
from django.core.handlers.wsgi import WSGIRequest

from lando.headless_api.models.automation_job import AutomationAction, AutomationJob
from lando.headless_api.models.tokens import ApiToken
from lando.main.admin import ReadOnlyInline
from lando.main.models import JobAdmin


class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("token_prefix", "user_email", "created_at")

    # Mark these fields as read-only in the admin.
    readonly_fields = ("token_prefix", "token_hash", "created_at")

    list_filter = ["created_at"]

    def user_email(self, instance: ApiToken) -> str:
        return instance.user.email


class AutomationActionJobInline(ReadOnlyInline):
    model = AutomationAction
    _target_object = "actions"
    readonly_fields = ("action_type", "data", "order")

    def has_add_permission(
        self, request: WSGIRequest, obj: AutomationAction | None = None
    ) -> bool:
        """Forbid addition of any action object from the inline interface."""
        return False

    def has_delete_permission(
        self, request: WSGIRequest, obj: AutomationAction | None = None
    ) -> bool:
        """Forbid deletion of any action object from the inline interface."""
        return False


class AutomationJobAdmin(JobAdmin):
    model = AutomationJob
    inlines = (AutomationActionJobInline,)
    readonly_fields = JobAdmin.readonly_fields + (
        "relbranch_name",
        "relbranch_commit_sha",
        "target_repo",
    )

    def action_types(self, instance: AutomationJob) -> str:
        """Return a summary string of the action types associated to a given job."""
        return str([a.action_type for a in instance.actions.all()])


class AutomationActionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "action_type",
        "job_id",
    )
    readonly_fields = ["job_id"]


admin.site.register(ApiToken, ApiTokenAdmin)
admin.site.register(AutomationAction, AutomationActionAdmin)
admin.site.register(AutomationJob, AutomationJobAdmin)
