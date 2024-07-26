from __future__ import annotations

import logging
from urllib.parse import urlparse

from django.conf import settings

from lando.api.legacy.systems import Subsystem

logger = logging.getLogger(__name__)


class LandoUISubsystem(Subsystem):
    name = "lando_ui"

    def ready(self) -> bool | str:
        url = urlparse(settings.LANDO_UI_URL)
        if not url.scheme or not url.netloc:
            return "Invalid LANDO_UI_URL, missing a scheme and/or hostname"

        return True


lando_ui_subsystem = LandoUISubsystem()
