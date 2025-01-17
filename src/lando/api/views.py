from functools import wraps
from typing import Callable

from django import forms
from django.http import JsonResponse
from django.views import View

from lando.main.models.revision import DiffWarning, DiffWarningStatus
from lando.utils.phabricator import get_phabricator_client


def phabricator_api_key_required(func: callable) -> Callable:
    """A simple wrapper that checks for a valid Phabricator API token."""

    @wraps(func)
    def _wrapper(self, request, *args, **kwargs):
        HEADER = "X-Phabricator-Api-Key"
        if HEADER not in request.headers:
            return JsonResponse({"error": f"{HEADER} missing."}, status=400)

        api_key = request.headers[HEADER]
        client = get_phabricator_client(api_key=api_key)
        has_valid_token = client.verify_api_token()

        if not has_valid_token:
            return JsonResponse({}, 401)

        return func(self, request, *args, **kwargs)

    return _wrapper


class LegacyDiffWarningView(View):
    """
    This class provides the API controllers for the legacy `DiffWarning` model.

    These API endpoints can be used by clients (such as Code Review bot) to
    get, create, or archive warnings.
    """

    @classmethod
    def _get_form(cls, method: str, data: dict):
        """Helper method to return validate data."""

        def data_validator(data):
            if not data or "message" not in data:
                raise forms.ValidationError(
                    "Provided data is missing the message value"
                )

        _forms = {
            # Used to filter DiffWarning objects.
            "GET": {
                "revision_id": forms.IntegerField(),
                "diff_id": forms.IntegerField(),
                "group": forms.CharField(),
            },
            # Used to create new DiffWarning objects.
            "POST": {
                "revision_id": forms.IntegerField(),
                "diff_id": forms.IntegerField(),
                "group": forms.CharField(),
                "data": forms.JSONField(validators=[data_validator]),
            },
        }
        return type(f"{cls.__name__}_{method}", (forms.Form,), _forms[method])(data)

    @phabricator_api_key_required
    def post(self, request):
        """Create a new `DiffWarning` based on provided revision and diff IDs.

        Args:
            data (dict): A dictionary containing data to store in the warning. `data`
                should contain at least a `message` key that contains the message to
                show in the warning.

        Returns:
            dict: a dictionary representation of the object that was created.
        """
        # TODO: validate whether revision/diff exist or not.
        form = self._get_form(request.method, request.POST)
        if form.is_valid():
            data = form.cleaned_data
            warning = DiffWarning(**data)
            warning.save()
            return JsonResponse(warning.serialize(), status=201)
        else:
            return JsonResponse({"errors": dict(form.errors)}, status=400)

    @phabricator_api_key_required
    def delete(self, request, diff_warning_id):
        """Archive a `DiffWarning` based on provided pk."""
        warning = DiffWarning.objects.get(pk=diff_warning_id)
        if not warning:
            return JsonResponse({}, status=404)

        warning.status = DiffWarningStatus.ARCHIVED
        warning.save()
        return JsonResponse(warning.serialize(), status=200)

    @phabricator_api_key_required
    def get(self, request, **kwargs):
        """Return a list of active revision diff warnings, if any."""
        form = self._get_form(request.method, request.GET)
        if form.is_valid():
            warnings = DiffWarning.objects.filter(**form.cleaned_data).all()
            return JsonResponse(
                [warning.serialize() for warning in warnings], status=200, safe=False
            )
        else:
            return JsonResponse({"errors": dict(form.errors)}, status=400)
