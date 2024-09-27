from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponseNotAllowed, JsonResponse

from lando.main.auth import require_authenticated_user
from lando.ui.legacy.forms import UserSettingsForm


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
        profile.clear_phabricator_api_key()
    else:
        profile.save_phabricator_api_key(form.cleaned_data["phabricator_api_key"])

    return JsonResponse({"success": True}, status=200)
