import re

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register

from lando.utils.phabricator import PhabricatorAPIException, PhabricatorClient

PHAB_API_KEY_RE = re.compile(r"^api-.{28}$")


class UtilsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lando.utils"


@register()
def phabricator_check(**kwargs) -> list[Error]:
    """Check validity of Phabricator settings and check connectivity."""
    errors = []

    unpriv_key = settings.PHABRICATOR_UNPRIVILEGED_API_KEY
    priv_key = settings.PHABRICATOR_ADMIN_API_KEY

    if unpriv_key and PHAB_API_KEY_RE.search(unpriv_key) is None:
        errors.append(
            "PHABRICATOR_UNPRIVILEGED_API_KEY has the wrong format, "
            'it must begin with "api-" and be 32 characters long.'
        )

    if priv_key and PHAB_API_KEY_RE.search(priv_key) is None:
        errors.append(
            "PHABRICATOR_ADMIN_API_KEY has the wrong format, "
            'it must begin with "api-" and be 32 characters long.'
        )

    if (unpriv_key or priv_key) and not errors:
        if unpriv_key:
            try:
                PhabricatorClient(
                    settings.PHABRICATOR_URL,
                    settings.PHABRICATOR_UNPRIVILEGED_API_KEY,
                ).call_conduit("conduit.ping")
            except PhabricatorAPIException as e:
                errors.append(f"PhabricatorAPIException: {e!s} (using unpriviledged key)")

        if priv_key:
            try:
                PhabricatorClient(
                    settings.PHABRICATOR_URL,
                    settings.PHABRICATOR_ADMIN_API_KEY,
                ).call_conduit("conduit.ping")
            except PhabricatorAPIException as e:
                errors.append(f"PhabricatorAPIException: {e!s} (using admin key)")

    return [Error(message) for message in errors]
