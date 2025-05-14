from django import forms
from django.contrib import admin
from django.db import models

from lando.headless_api.models.automation_job import AutomationAction, AutomationJob
from lando.headless_api.models.tokens import ApiToken
from lando.main.admin import ReadOnlyInline


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

    def formfield_for_dbfield(self, db_field: models.Field, **kwargs) -> forms.Field:
        """
        Forbid alteration of the JobAction list.
        """
        formfield = super(ReadOnlyInline, self).formfield_for_dbfield(
            db_field, **kwargs
        )
        if db_field.name == "actions":
            formfield.widget.can_add_related = False
            formfield.widget.can_change_related = False
            formfield.widget.can_delete_related = False
        return formfield


class AutomationJobAdmin(admin.ModelAdmin):
    model = AutomationJob
    list_display = (
        "id",
        "status",
        "target_repo__name",
        "action_types",
        "created_at",
        "requester_email",
        "duration_seconds",
    )
    list_filter = ("target_repo__name", "requester_email", "created_at")
    inlines = [AutomationActionJobInline]

    def has_add_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        """Forbid addition of any action object from the inline interface."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        """Forbid change of any action object from the inline interface."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        """Forbid deletion of any action object from the inline interface."""
        return False

    def action_types(self, instance: AutomationJob) -> str:
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
