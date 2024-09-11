from django.apps import AppConfig
from django.conf import settings

from lando.main.sentry import init_sentry


class MainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lando.main"

    def ready(self):
        """Run initialization tasks."""
        if settings.ENVIRONMENT.is_remote:
            init_sentry()
