import re

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register

from lando.utils.phabricator import PhabricatorAPIException, PhabricatorClient

PHAB_API_KEY_RE = re.compile(r"^api-.{28}$")

PHAB_API_KEY_FORMAT_ERROR_TEMPLATE = (
    '{} has the wrong format it must begin with "api-" and be 32 characters long.'
)


class UtilsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lando.utils"


@register()
def phabricator_check(**kwargs) -> list[Error]:
    """Check validity of Phabricator settings and check connectivity."""
    errors = []

    unprivileged_key = settings.PHABRICATOR_UNPRIVILEGED_API_KEY
    admin_key = settings.PHABRICATOR_ADMIN_API_KEY

    if unprivileged_key and PHAB_API_KEY_RE.search(unprivileged_key) is None:
        errors.append(
            PHAB_API_KEY_FORMAT_ERROR_TEMPLATE.format(
                "PHABRICATOR_UNPRIVILEGED_API_KEY"
            )
        )

    if admin_key and PHAB_API_KEY_RE.search(admin_key) is None:
        errors.append(
            PHAB_API_KEY_FORMAT_ERROR_TEMPLATE.format("PHABRICATOR_ADMIN_API_KEY")
        )

    if (unprivileged_key or admin_key) and not errors:
        if unprivileged_key:
            try:
                PhabricatorClient(
                    settings.PHABRICATOR_URL,
                    settings.PHABRICATOR_UNPRIVILEGED_API_KEY,
                ).call_conduit("conduit.ping")
            except PhabricatorAPIException as e:
                errors.append(
                    f"PhabricatorAPIException: {e!s} (using unpriviledged key)"
                )

        if admin_key:
            try:
                PhabricatorClient(
                    settings.PHABRICATOR_URL,
                    settings.PHABRICATOR_ADMIN_API_KEY,
                ).call_conduit("conduit.ping")
            except PhabricatorAPIException as e:
                errors.append(f"PhabricatorAPIException: {e!s} (using admin key)")

    return [Error(message) for message in errors]
