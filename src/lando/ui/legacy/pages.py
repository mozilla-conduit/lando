import logging

from django.template.response import TemplateResponse

from lando.ui.views import LandoView

logger = logging.getLogger(__name__)


class Index(LandoView):
    def get(self, request):
        return TemplateResponse(request=request, template="home.html")
