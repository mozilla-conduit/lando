from lando.environments import Environment
from lando.settings import *  # noqa: F403

OIDC_DOMAIN = "lando-api.auth0.test"
OIDC_OP_TOKEN_ENDPOINT = f"{OIDC_DOMAIN}/oauth/token"
OIDC_OP_USER_ENDPOINT = f"{OIDC_DOMAIN}/userinfo"
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{OIDC_DOMAIN}/authorize"
OIDC_REDIRECT_REQUIRE_HTTPS = True

OIDC_IDENTIFIER = (
    "lando-api"  # Added for compatibility with tests, should not be needed.
)
PHABRICATOR_URL = "http://phabricator.test"
PHABRICATOR_ADMIN_API_KEY = "api-thiskeymustbe32characterslen"
PHABRICATOR_UNPRIVILEGED_API_KEY = "api-thiskeymustbe32characterslen"
CELERY_TASK_ALWAYS_EAGER = True
ENVIRONMENT = Environment.test

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

DEFAULT_FROM_EMAIL = "Lando <lando@lando.test>"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

LANDING_WORKER_DEFAULT_GRACE_SECONDS = 0

# Disable django-compressor's SCSS compilation in tests. Both settings are
# needed: render_compressed only skips compilation when COMPRESS_ENABLED is
# False *and* COMPRESS_PRECOMPILERS is empty. Without clearing precompilers,
# the compress template tag still invokes `npx sass --load-path=node_modules`,
# which fails when node_modules is not present (e.g. local Docker via volume
# mount hiding the image's node_modules).
COMPRESS_ENABLED = False
COMPRESS_PRECOMPILERS = ()
