from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register

from lando.main.sentry import init_sentry


class MainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lando.main"

    def ready(self):
        """Run initialization tasks."""
        init_sentry()


@register(deploy=True)
def pulse_check(app_configs: list[AppConfig], **kwargs) -> list[Error]:
    errors = []
    if settings.PULSE_HOST.startswith("memory"):
        message = (
            "PULSE_HOST set to a `memory` location. "
            + str(settings.PULSE_HOST)
            + "This should not be the case in non-local deployments. "
            + settings.ENVIRONMENT
        )
        if settings.ENVIRONMENT.is_remote:
            errors.append(Error(message))
        else:
            errors.append(Warning(message))
    return errors
