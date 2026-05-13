from django.template.response import TemplateResponse
from django.views import View

from lando.utils.views import BaseLandoViewMixin


class LandoView(View, BaseLandoViewMixin):
    """A base class for UI views."""

    response_class = TemplateResponse
