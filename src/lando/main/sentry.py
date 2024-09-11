import logging

import sentry_sdk
from django.conf import settings
from sentry_sdk.integrations.django import DjangoIntegration

from lando.version import version

logger = logging.getLogger(__name__)


def init_sentry():
    """Initialize Sentry integration for remote environments."""
    if not settings.ENVIRONMENT.is_remote:
        raise ValueError(
            "Attempting to initialize Sentry in non-remote environment "
            f"({settings.ENVIRONMENT})"
        )
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[DjangoIntegration()],
        traces_sample_rate=1.0,
        release=version,
    )
