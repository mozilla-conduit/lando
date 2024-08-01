import logging

from lando.ui.views import LandoView
from django.template.response import TemplateResponse

logger = logging.getLogger(__name__)


class Index(LandoView):
    def get(self, request):
        return TemplateResponse(request=request, template="home.html")
