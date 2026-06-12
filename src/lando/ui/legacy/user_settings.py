import logging

from django.core.handlers.wsgi import WSGIRequest
from django.db import IntegrityError
from django.http import HttpResponseNotAllowed, JsonResponse

from lando.main.auth import require_authenticated_user
from lando.main.models.profile import Profile
from lando.ui.legacy.forms import UserSettingsForm
from lando.utils.phabricator import get_phabricator_client

logger = logging.getLogger(__name__)


def phid_conflict_response(phid: str) -> JsonResponse:
    """Return a 400 response indicating the PHID is owned by another account."""
    logger.info(
        "Phabricator PHID `%s` is already linked to another Lando account.",
        phid,
    )
    return JsonResponse(
        {
            "errors": {
                "phabricator_api_key": [
                    "This Phabricator account is already linked to another Lando user."
                ]
            }
        },
        status=400,
    )


@require_authenticated_user
def manage_api_key(request: WSGIRequest) -> JsonResponse:
    """Sets `phabricator-api-token` cookie from the UserSettingsForm.

    Sets the cookie to the value provided in `phabricator_api_key` field.
    If `reset_key` is `True` cookie is set to an empty string.
    """
    if not request.method == "POST":
        return HttpResponseNotAllowed()

    form = UserSettingsForm(request.POST)

    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    profile = request.user.profile
    if form.cleaned_data["reset_key"]:
        profile.clear_phabricator_elements()
    else:
        api_key = form.cleaned_data["phabricator_api_key"]

        logger.debug("Verifying Phabricator API key via `user.whoami`.")
        phab = get_phabricator_client(api_key=api_key)
        whoami = phab.verify_api_token()
        if not whoami:
            return JsonResponse(
                {"errors": {"phabricator_api_key": ["Invalid API key."]}},
                status=400,
            )

        phid = whoami["phid"]
        logger.debug("Phabricator API key verified for PHID `%s`.", phid)

        if (
            Profile.objects.filter(phabricator_phid=phid)
            .exclude(pk=profile.pk)
            .exists()
        ):
            return phid_conflict_response(phid)

        try:
            profile.save_phabricator_elements(api_key, phid=phid)
        except IntegrityError:
            return phid_conflict_response(phid)

    return JsonResponse({"success": True}, status=200)
