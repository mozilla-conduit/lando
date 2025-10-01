import logging

from django.template.response import TemplateResponse

from lando.ui.views import LandoView

logger = logging.getLogger(__name__)


class IndexView(LandoView):
    def get(self, request):  # noqa: ANN001, ANN201
        return TemplateResponse(request=request, template="home.html")
