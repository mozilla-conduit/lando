import logging

from django.contrib.auth.models import User
from django.core.handlers.wsgi import WSGIRequest
from ninja.security import HttpBearer

# requests is a transitive dependency of mozilla-django-oidc.
from requests.exceptions import HTTPError

from lando.main.auth import LandoOIDCAuthenticationBackend

logger = logging.getLogger(__name__)


class AccessTokenAuth(HttpBearer):
    """Ninja bearer token-based authenticator delegating verification to the OIDC backend."""

    def authenticate(self, request: WSGIRequest, token: str) -> User:
        """Forward the authenticate request to the LandoOIDCAuthenticationBackend."""
        # The token is extracted in the LandoOIDCAuthenticationBackend, so we don't need
        # to pass it. But we need to inherit from HttpBearer for Auth to work.

        oidc_auth = LandoOIDCAuthenticationBackend()

        #
        # BEGIN BORROW FROM https://github.com/mozilla/mozilla-django-oidc/pull/551
        #

        # If a bearer token is present in the request, use it to authenticate the user.
        if authorization := request.META.get("HTTP_AUTHORIZATION"):
            scheme, token = authorization.split(maxsplit=1)
            if scheme.lower() == "bearer":
                # get_or_create_user and get_userinfo uses neither id_token nor payload.
                # XXX: maybe we only want to _get_ the user, and not create the if they
                # aren't alrealdy registered.
                try:
                    return oidc_auth.get_or_create_user(token, None, None)
                except HTTPError as exc:
                    if exc.response.status_code in [401, 403]:
                        logger.warning(
                            "failed to authenticate user from bearer token: %s", exc
                        )
                        return None
                    raise exc
        #
        # END BORROW FROM https://github.com/mozilla/mozilla-django-oidc/pull/551
        #

        return oidc_auth.authenticate(request)
