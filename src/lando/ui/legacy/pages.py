import logging

from django.core.handlers.wsgi import WSGIRequest
from django.template.response import TemplateResponse

from lando.ui.views import LandoView

logger = logging.getLogger(__name__)


class IndexView(LandoView):
    def get(self, request: WSGIRequest) -> TemplateResponse:
        return TemplateResponse(request=request, template="home.html")
