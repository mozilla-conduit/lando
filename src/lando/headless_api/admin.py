from django.contrib import admin

from lando.headless_api.models.automation_job import AutomationAction, AutomationJob
from lando.headless_api.models.tokens import ApiToken


class ApiTokenAdmin(admin.ModelAdmin):

    list_display = ("user", "token_prefix", "created_at")

    # Mark these fields as read-only in the admin.
    readonly_fields = ("token_prefix", "token_hash", "created_at")


admin.site.register(ApiToken, ApiTokenAdmin)
admin.site.register(AutomationJob, admin.ModelAdmin)
admin.site.register(AutomationAction, admin.ModelAdmin)
