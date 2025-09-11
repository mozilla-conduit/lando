from django.contrib import admin
from django.core.handlers.wsgi import WSGIRequest

from lando.main.admin import JobAdmin, ReadOnlyInline
from lando.try_api.models.job import TryAction, TryJob


class TryActionJobInline(ReadOnlyInline):
    model = TryAction
    _target_object = "actions"
    readonly_fields = ("action_type", "data", "order")

    def has_add_permission(
        self, request: WSGIRequest, obj: TryAction | None = None
    ) -> bool:
        """Forbid addition of any action object from the inline interface."""
        return False

    def has_delete_permission(
        self, request: WSGIRequest, obj: TryAction | None = None
    ) -> bool:
        """Forbid deletion of any action object from the inline interface."""
        return False


class TryJobAdmin(JobAdmin):
    model = TryJob
    inlines = (TryActionJobInline,)


admin.site.register(TryJob, TryJobAdmin)
admin.site.register(TryAction, admin.ModelAdmin)  # noqa: F821
