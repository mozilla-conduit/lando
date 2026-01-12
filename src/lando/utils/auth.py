import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.security import HttpBearer

# requests is a transitive dependency of mozilla-django-oidc.
from requests.exceptions import HTTPError

from lando.main.auth import LandoOIDCAuthenticationBackend

logger = logging.getLogger(__name__)


class AccessTokenLandoOIDCAuthenticationBackend(LandoOIDCAuthenticationBackend):
    """A shim of the LandoOIDCAuthenticationBackend, borrowing code from mozilla-django-oidc#551.

    https://github.com/mozilla/mozilla-django-oidc/pull/551"""

    def authenticate(self, request: WSGIRequest, **kwargs) -> User:
        # If a bearer token is present in the request, use it to authenticate the user.
        if authorization := request.META.get("HTTP_AUTHORIZATION"):
            scheme, token = authorization.split(maxsplit=1)
            if scheme.lower() == "bearer":
                # get_or_create_user and get_userinfo uses neither id_token nor payload.
                # XXX: maybe we only want to _get_ the user, and not create the if they
                # aren't alrealdy registered.
                try:
                    return self.get_or_create_user(token, None, None)
                except HTTPError as exc:
                    if exc.response.status_code in [401, 403]:
                        logger.warning(
                            "failed to authenticate user from bearer token: %s", exc
                        )
                        return None
                    raise exc

        return super().authenticate(request, **kwargs)


class AccessTokenAuth(HttpBearer):
    """Ninja bearer token-based authenticator delegating verification to the OIDC backend."""

    def authenticate(self, request: WSGIRequest, token: str) -> User:
        """Forward the authenticate request to the LandoOIDCAuthenticationBackend."""
        # The token is extracted in the LandoOIDCAuthenticationBackend, so we don't need
        # to pass it. But we need to inherit from HttpBearer for auth to work with Ninja.
        oidc_auth = AccessTokenLandoOIDCAuthenticationBackend()

        # Django-Ninja sets `request.auth` to the verified token, since
        # some APIs may have authentication without user management. Our
        # access tokens always correspond to a specific user, so set that on
        # the request here.
        request.user = oidc_auth.authenticate(request)

        return request.user


def user_has_direct_permission(user: User, permission: str) -> bool:
    """
    Test that the user has permission directly rather than inherited.

    This prevents giving superusers LDAP-based permissions they shouldn't have.


    Parameters:

    user: User
        Django User model

    permission: str
        Permission string to check. It should not contain a namespace prefix, which is
        assumed to be `main`.

    Returns:
        bool: whether the user has the permission
    """
    if user.is_superuser:
        # We can't rely on the `get_user_permissions()` method, as it returns all existing
        # permissions for superusers. Here, we want to check permissions that have been
        # explicitely given to the user from LDAP groups.
        if user.user_permissions.filter(codename=permission):
            return True
    else:
        # If the user is not a superuser, we can skip the DB round-trip.
        if f"main.{permission}" in user.get_user_permissions():
            return True


#
# Simple API exposing an authenticated endpoint providing OAuth info.
#

api = NinjaAPI(urls_namespace="auth", auth=AccessTokenAuth())


@api.get("/__userinfo__")
def userinfo(request: WSGIRequest) -> JsonResponse:
    """Test endpoint to check token verification.

    Only available in non-prod environments."""
    if not settings.ENVIRONMENT.is_lower:
        raise HttpError(404, "Not Found")
    return JsonResponse({"user_id": str(request.auth)})
