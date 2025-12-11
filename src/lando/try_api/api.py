import logging

from ninja import NinjaAPI

from lando.utils.auth import AccessTokenAuth

logger = logging.getLogger(__name__)

api = NinjaAPI(urls_namespace="try", auth=AccessTokenAuth())
