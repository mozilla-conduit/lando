# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import logging.config
import os
from typing import Any

import connexion
from connexion.resolver import RestyResolver

from lando.api.legacy.auth import auth0_subsystem
from lando.api.legacy.cache import cache_subsystem
from lando.api.legacy.dockerflow import dockerflow
from lando.api.legacy.hooks import initialize_hooks
from lando.api.legacy.logging import logging_subsystem
from lando.api.legacy.phabricator import phabricator_subsystem
from lando.api.legacy.sentry import sentry_subsystem
from lando.api.legacy.smtp import smtp_subsystem
from lando.api.legacy.systems import Subsystem
from lando.api.legacy.treestatus import treestatus_subsystem
from lando.api.legacy.ui import lando_ui_subsystem
from lando.api.legacy.version import version

logger = logging.getLogger(__name__)

# Subsystems shared across different services
SUBSYSTEMS: list[Subsystem] = [
    # Logging & sentry first so that other systems log properly.
    logging_subsystem,
    sentry_subsystem,
    auth0_subsystem,
    cache_subsystem,
    lando_ui_subsystem,
    phabricator_subsystem,
    smtp_subsystem,
    treestatus_subsystem,
]


def load_config() -> dict[str, Any]:
    """Return configuration pulled from the environment."""
    config = {
        "ALEMBIC": {"script_location": "/migrations/"},
        "ENVIRONMENT": os.getenv("ENV"),
        "MAIL_SUPPRESS_SEND": bool(os.getenv("MAIL_SUPPRESS_SEND")),
        "MAIL_USE_SSL": bool(os.getenv("MAIL_USE_SSL")),
        "MAIL_USE_TLS": bool(os.getenv("MAIL_USE_TLS")),
        "VERSION": version(),
    }

    config_keys = (
        "BUGZILLA_API_KEY",
        "BUGZILLA_URL",
        "CACHE_REDIS_DB",
        "CACHE_REDIS_HOST",
        "CACHE_REDIS_PASSWORD",
        "CACHE_REDIS_PORT",
        "CSP_REPORTING_URL",
        "LANDO_UI_URL",
        "LOG_LEVEL",
        "MAIL_FROM",
        "MAIL_PASSWORD",
        "MAIL_PORT",
        "MAIL_RECIPIENT_WHITELIST",
        "MAIL_SERVER",
        "MAIL_USERNAME",
        "OIDC_DOMAIN",
        "OIDC_IDENTIFIER",
        "PHABRICATOR_ADMIN_API_KEY",
        "PHABRICATOR_UNPRIVILEGED_API_KEY",
        "PHABRICATOR_URL",
        "REPO_CLONES_PATH",
        "REPOS_TO_LAND",
        "SENTRY_DSN",
        "TREESTATUS_URL",
    )

    defaults = {
        "CACHE_REDIS_PORT": 6379,
        "LOG_LEVEL": "INFO",
        "MAIL_FROM": "mozphab-prod@mozilla.com",
        "REPO_CLONES_PATH": "/repos",
        "TREESTATUS_URL": "https://treestatus.mozilla-releng.net",
    }

    for key in config_keys:
        config[key] = os.getenv(key, defaults.get(key))

    return config


def construct_app(config: dict[str, Any]) -> connexion.App:
    app = connexion.App(__name__, specification_dir="spec/")

    app.add_api(
        "swagger.yml",
        resolver=RestyResolver("landoapi.api"),
        options={"swagger_ui": False},
    )
    flask_app = app.app
    flask_app.config.update(config)
    flask_app.register_blueprint(dockerflow)
    initialize_hooks(flask_app)

    return app
