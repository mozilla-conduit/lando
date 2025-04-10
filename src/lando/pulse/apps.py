from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register


class PulseConfig(AppConfig):
    name = "lando.pulse"


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
