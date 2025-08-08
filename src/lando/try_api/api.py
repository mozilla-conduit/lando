import logging

from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.security import HttpBearer

from lando.main.auth import LandoOIDCAuthenticationBackend

logger = logging.getLogger(__name__)


class GlobalAuth(HttpBearer):
    def authenticate(self, request: WSGIRequest, token: str) -> User:
        # The token is extracted in the LandoOIDCAuthenticationBackend, so we don't need
        # to pass it. But we need to inherit from HttpBearer for Auth to work.
        oidc_auth = LandoOIDCAuthenticationBackend()
        return oidc_auth.authenticate(request)


api = NinjaAPI(urls_namespace="try", auth=GlobalAuth())


@api.get("/__userinfo__")
def userinfo(request: WSGIRequest) -> JsonResponse:
    if not settings.ENVIRONMENT.is_lower():
        raise HttpError(404, "Not Found")
    return JsonResponse({"token": str(request.auth)})
