import logging

from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI
from ninja.security import HttpBearer
from requests.exceptions import HTTPError

from lando.main.auth import LandoOIDCAuthenticationBackend

logger = logging.getLogger(__name__)


class GlobalAuth(LandoOIDCAuthenticationBackend, HttpBearer):
    pass
    # def authenticate(self, _request: WSGIRequest, token: str):
    #     try:
    #         super(LandoOIDCAuthenticationBackend, self).get_userinfo(
    #             access_token=token, id_token=None, payload=None
    #         )
    #     except HTTPError as exc:
    #         logger.exception(exc)
    #         return None


api = NinjaAPI(urls_namespace="try", auth=GlobalAuth())


@api.get("/__userinfo__")
def userinfo(request) -> JsonResponse:
    return JsonResponse({"token": "supersecret"})
