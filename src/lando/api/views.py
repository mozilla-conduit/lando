import json
from functools import wraps
from typing import Callable

from django import forms
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from lando.main.models.commit import CommitMap
from lando.main.models.revision import DiffWarning, DiffWarningStatus
from lando.main.scm import (
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
)
from lando.utils.phabricator import get_phabricator_client


def phabricator_api_key_required(func: callable) -> Callable:
    """A simple wrapper that checks for a valid Phabricator API token."""

    @wraps(func)
    def _wrapper(self, request, *args, **kwargs):  # noqa: ANN001
        HEADER = "X-Phabricator-API-Key"
        if HEADER not in request.headers:
            return JsonResponse({"error": f"{HEADER} missing."}, status=400)

        api_key = request.headers[HEADER]
        client = get_phabricator_client(api_key=api_key)
        has_valid_token = client.verify_api_token()

        if not has_valid_token:
            return JsonResponse({}, 401)

        return func(self, request, *args, **kwargs)

    return _wrapper


@method_decorator(csrf_exempt, name="dispatch")
class LegacyDiffWarningView(View):
    """
    This class provides the API controllers for the legacy `DiffWarning` model.

    These API endpoints can be used by clients (such as Code Review bot) to
    get, create, or archive warnings.
    """

    @phabricator_api_key_required
    def post(self, request):  # noqa: ANN001, ANN201
        """Create a new `DiffWarning` based on provided revision and diff IDs.

        Args:
            data (dict): A dictionary containing data to store in the warning. `data`
                should contain at least a `message` key that contains the message to
                show in the warning.

        Returns:
            dict: a dictionary representation of the object that was created.
        """

        class Form(forms.Form):
            def data_validator(data):
                if not data or "message" not in data:
                    raise forms.ValidationError(
                        "Provided data is missing the message value"
                    )

            revision_id = forms.IntegerField()
            diff_id = forms.IntegerField()
            group = forms.CharField()
            data = forms.JSONField(validators=[data_validator])

        # TODO: validate whether revision/diff exist or not.
        form = Form(json.loads(request.body))
        if form.is_valid():
            data = form.cleaned_data
            warning = DiffWarning.objects.create(**data)
            return JsonResponse(warning.serialize(), status=201)

        return JsonResponse({"errors": dict(form.errors)}, status=400)

    @phabricator_api_key_required
    def delete(self, request, diff_warning_id):  # noqa: ANN001, ANN201
        """Archive a `DiffWarning` based on provided pk."""
        warning = DiffWarning.objects.get(pk=diff_warning_id)
        if not warning:
            return JsonResponse({}, status=404)

        warning.status = DiffWarningStatus.ARCHIVED
        warning.save()
        return JsonResponse(warning.serialize(), status=200)

    @phabricator_api_key_required
    def get(self, request, **kwargs):  # noqa: ANN001, ANN201
        """Return a list of active revision diff warnings, if any."""

        class Form(forms.Form):
            revision_id = forms.IntegerField()
            diff_id = forms.IntegerField()
            group = forms.CharField()

        form = Form(request.GET)
        if form.is_valid():
            warnings = DiffWarning.objects.filter(**form.cleaned_data).all()
            return JsonResponse(
                [warning.serialize() for warning in warnings], status=200, safe=False
            )

        return JsonResponse({"errors": dict(form.errors)}, status=400)


class CommitMapBaseView(View):
    """CommitMap base view to be extended for bidirectional git - hg mapping."""

    def get(
        self, request: WSGIRequest, git_repo_name: str, commit_hash: str
    ) -> JsonResponse:
        hash_field = f"{self.scm}_hash"
        filters = {hash_field: commit_hash, "git_repo_name": git_repo_name}
        commits = CommitMap.objects.filter(**filters)

        if not commits.exists():
            CommitMap.catch_up(git_repo_name)

        if commits.count() == 1:
            commit = commits.first()
            return JsonResponse(commit.serialize(), status=200)
        elif commits.count() > 1:
            return JsonResponse(
                {"error": f"Multiple commits found ({commits.count()})"}, status=400
            )
        return JsonResponse({"error": "No commits found"}, status=404)


@method_decorator(csrf_exempt, name="dispatch")
class git2hgCommitMapView(CommitMapBaseView):
    """Return corresponding CommitMap given a git hash."""

    scm = SCM_TYPE_GIT


@method_decorator(csrf_exempt, name="dispatch")
class hg2gitCommitMapView(CommitMapBaseView):
    """Return corresponding CommitMap given an hg hash."""

    scm = SCM_TYPE_HG
