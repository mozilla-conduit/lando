from lando.settings import *


OIDC_DOMAIN = "lando-api.auth0.test"
OIDC_OP_TOKEN_ENDPOINT = f"{OIDC_DOMAIN}/oauth/token"
OIDC_OP_USER_ENDPOINT = f"{OIDC_DOMAIN}/userinfo"
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{OIDC_DOMAIN}/authorize"
OIDC_REDIRECT_REQUIRE_HTTPS = True

OIDC_IDENTIFIER = (
    "lando-api"  # Added for compatibility with tests, should not be needed.
)
GITHUB_ACCESS_TOKEN = ""
PHABRICATOR_URL = "http://phabricator.test"
PHABRICATOR_ADMIN_API_KEY = "api-thiskeymustbe32characterslen"
PHABRICATOR_UNPRIVILEGED_API_KEY = "api-thiskeymustbe32characterslen"
CELERY_TASK_ALWAYS_EAGER = True
ENVIRONMENT = "test"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}
