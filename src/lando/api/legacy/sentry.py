import logging

import sentry_sdk
from django.conf import settings
from sentry_sdk.integrations.django import DjangoIntegration

from lando.api.legacy.systems import Subsystem

logger = logging.getLogger(__name__)


def sanitize_headers(headers: dict):
    sensitive_keys = ("X-PHABRICATOR-API-KEY",)
    for key in headers:
        if key.upper() in sensitive_keys:
            headers[key] = 10 * "*"


def before_send(event: dict, *args) -> dict:
    if "request" in event and "headers" in event["request"]:
        sanitize_headers(event["request"]["headers"])
    return event


class SentrySubsystem(Subsystem):
    name = "sentry"

    def init_app(self, app):
        super().init_app(app)

        sentry_dsn = settings.SENTRY_DSN
        logger.info("sentry status", extra={"enabled": bool(sentry_dsn)})
        sentry_sdk.init(
            before_send=before_send,
            dsn=sentry_dsn,
            integrations=[DjangoIntegration()],
            traces_sample_rate=1.0,
            release=self.settings.VERSION.get("version", "0.0.0"),
        )


sentry_subsystem = SentrySubsystem()
