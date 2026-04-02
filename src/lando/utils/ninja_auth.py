import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import APIKeyHeader, HttpBearer
from typing_extensions import override

from lando.main.auth import AccessTokenLandoOIDCAuthenticationBackend
from lando.utils.phabricator import PHABRICATOR_API_KEY_HEADER

logger = logging.getLogger(__name__)


class AccessTokenAuth(HttpBearer):
    """Ninja bearer token-based authenticator delegating verification to the OIDC backend."""

    @override
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


#
# Simple API exposing an authenticated endpoint providing OAuth info.
#

api = NinjaAPI(urls_namespace="auth", auth=AccessTokenAuth())


class ApiError(Schema):
    """Error response format."""

    details: str


class PhabricatorTokenAuth(APIKeyHeader):
    """Verify that the Phabricator middleware authenticated the request.

    The `PhabricatorTokenAuthenticationMiddleware` reads the
    `X-Phabricator-API-Key` header and authenticates the user via the
    `PhabricatorTokenAuthenticationBackend`, setting `request.user`.
    This auth class simply verifies that the user was authenticated.
    """

    param_name = PHABRICATOR_API_KEY_HEADER

    def authenticate(self, request: WSGIRequest, key: str | None) -> str | None:
        """Return the API key if the middleware authenticated the user, `None` otherwise."""
        if not key or not request.user.is_authenticated:
            return None

        return key


@api.get("/__userinfo__")
def userinfo(request: WSGIRequest) -> JsonResponse:
    """Test endpoint to check token verification.

    Only available in non-prod environments."""
    if not settings.ENVIRONMENT.is_lower:
        raise HttpError(404, "Not Found")
    return JsonResponse({"user_id": str(request.auth)})
