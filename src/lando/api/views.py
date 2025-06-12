import json
from functools import wraps
from typing import Callable

import requests
from django import forms
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from lando.main.models.commit import CommitMap
from lando.main.models.repo import Repo
from lando.main.models.revision import DiffWarning, DiffWarningStatus
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
    def _find_last_node(self, git_repo_name: str) -> CommitMap:
        return CommitMap.objects.filter(git_repo_name=git_repo_name).latest(
            "created_at"
        )

    def find_last_hg_node(self, git_repo_name: Repo) -> CommitMap:
        return self._find_last_node(git_repo_name).hg_hash

    def catch_up(self, git_repo_name: str, hg_repo_name: str):
        # Fetch last node, and fetch all pushlog entries from hgmo to process them.
        commit_hash = self.find_last_hg_node(git_repo_name)
        self.fetch_push_data(
            hg_repo_name=hg_repo_name,
            git_repo_name=git_repo_name,
            fromchangeset=commit_hash,
        )

    def fetch_push_data(self, hg_repo_name: str, git_repo_name: str, **kwargs) -> dict:
        hg_repo = Repo.objects.get(hg_repo_name=hg_repo_name)
        url = f"{hg_repo.url}/json-pushes"
        # url = "https://hg-edge.mozilla.org/integration/autoland/json-pushes"
        push_data = requests.get(url, params=kwargs).json()

        # We don't care about the key, as it is just the build ID.
        # NOTE: multiple changesets may be included in the response.
        for push in list(push_data.values()):
            changesets = push["changesets"]
            git_changesets = push["git_changesets"]
            if len(changesets) != len(git_changesets):
                raise ValueError(
                    "Number of changesets does not match number of git changesets: "
                    f"{len(changesets)} vs {len(git_changesets)}"
                )
            for i in range(len(changesets)):
                params = {
                    "hg_hash": changesets[i],
                    "git_hash": git_changesets[i],
                    "git_repo_name": git_repo_name,
                    "hg_repo_name": hg_repo_name,
                }
                if not CommitMap.objects.filter(**params).exists():
                    CommitMap.objects.create(**params)

    def get(self, request: WSGIRequest, commit_hash: str, **kwargs) -> JsonResponse:
        if hg_repo_name := kwargs.get("hg_repo_name"):
            git_repo_name = CommitMap.get_git_repo_name(hg_repo_name)
        elif git_repo_name := kwargs.get("git_repo_name"):
            hg_repo_name = CommitMap.get_hg_repo_name(git_repo_name)

        filters = {self.hash_field: commit_hash, "git_repo_name": git_repo_name}
        commits = CommitMap.objects.filter(**filters)

        if not commits.exists():
            # Commit either does not exist or has not been encountered before.
            # TODO: check if commit is valid (git or hg).
            self.catch_up(git_repo_name, hg_repo_name)

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
    hash_field = "git_hash"


@method_decorator(csrf_exempt, name="dispatch")
class hg2gitCommitMapView(CommitMapBaseView):
    hash_field = "hg_hash"
