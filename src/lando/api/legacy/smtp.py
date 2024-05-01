# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
from contextlib import contextmanager

from django.conf import settings
from lando.api.legacy.systems import Subsystem

logger = logging.getLogger(__name__)


class SMTP:
    def __init__(self, app=None):
        self.flask_app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.flask_app = app

    @property
    def suppressed(self):
        return (
            self.flask_app is None
            or bool(settings.MAIL_SUPPRESS_SEND)
            or not settings.MAIL_SERVER
        )

    @property
    def default_from(self):
        return settings.MAIL_FROM or "mozphab-prod@mozilla.com"

    @contextmanager
    def connection(self):
        if self.suppressed:
            raise ValueError("Supressed SMTP has no connection")

        host = settings.MAIL_SERVER or None
        port = settings.MAIL_PORT or None
        use_ssl = settings.MAIL_USE_SSL
        use_tls = settings.MAIL_USE_TLS

        username = settings.MAIL_USERNAME or None
        password = settings.MAIL_PASSWORD or None

        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        c = smtp_class(host, port)

        try:
            if use_tls:
                c.starttls()
            if username and password:
                c.login(username, password)
            yield c
        finally:
            c.close()

    def recipient_allowed(self, email):
        if self.flask_app is None:
            return True

        whitelist = settings.MAIL_RECIPIENT_WHITELIST or None
        if whitelist is None:
            return True

        return email in whitelist


smtp = SMTP()


class SMTPSubsystem(Subsystem):
    name = "SMTP"

    def init_app(self, app):
        super().init_app(app)
        smtp.init_app(app)

    def ready(self):
        if smtp.suppressed:
            logger.warning(
                "SMTP is suppressed, assuming ready",
                extra={
                    "MAIL_SERVER": settings.MAIL_SERVER,
                    "MAIL_SUPPRESS_SEND": settings.MAIL_SUPPRESS_SEND,
                },
            )
            return True

        # Attempt an smtp connection.
        with smtp.connection():
            return True


smtp_subsystem = SMTPSubsystem()
