import json
from collections import defaultdict
from datetime import datetime
from functools import wraps
from typing import Callable

from django import forms
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from lando.main.models import (
    CommitMap,
    JobStatus,
    LandingJob,
    Repo,
    Revision,
    add_revisions_to_job,
)
from lando.main.models.revision import DiffWarning, DiffWarningStatus
from lando.main.scm import (
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
)
from lando.utils.github import GitHubAPIClient, PullRequest
from lando.utils.phabricator import get_phabricator_client


class APIView(View):
    """A base class for API views."""

    pass


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

    scm: str

    def get(
        self, request: WSGIRequest, git_repo_name: str, commit_hash: str
    ) -> JsonResponse:
        try:
            commit = CommitMap.map_hash_from(self.scm, git_repo_name, commit_hash)
        except CommitMap.DoesNotExist as exc:
            error_detail = f"No commit found in {self.scm} for {commit_hash} in {git_repo_name}: {exc}"
            return JsonResponse(
                {"error": "No commits found", "detail": error_detail}, status=404
            )
        except CommitMap.MultipleObjectsReturned as exc:
            error_detail = f"Multiple commits found in {self.scm} for {commit_hash} in {git_repo_name}: {exc}"
            return JsonResponse(
                {"error": "Multiple commits found", "detail": error_detail}, status=400
            )

        return JsonResponse(commit.serialize(), status=200)


@method_decorator(csrf_exempt, name="dispatch")
class git2hgCommitMapView(CommitMapBaseView):
    """Return corresponding CommitMap given a git hash."""

    scm = SCM_TYPE_GIT


@method_decorator(csrf_exempt, name="dispatch")
class hg2gitCommitMapView(CommitMapBaseView):
    """Return corresponding CommitMap given an hg hash."""

    scm = SCM_TYPE_HG


class LandingJobPullRequestAPIView(View):
    """Handle pull request landing jobs in the API."""

    def get(
        self, request: WSGIRequest, repo_name: int, pull_number: int
    ) -> JsonResponse:
        """Return the status of a pull request based on landing job counts."""

        target_repo = Repo.objects.get(name=repo_name)
        client = GitHubAPIClient(target_repo)
        pull_request = PullRequest(client.get_pull_request(pull_number), target_repo)
        landing_jobs = defaultdict(list)
        for landing_job in pull_request.landing_jobs:
            landing_jobs[landing_job.status].append(landing_job.id)

        status = None
        # Return the first encountered status in this list.
        for _status in [
            JobStatus.LANDED,
            JobStatus.CREATED,
            JobStatus.SUBMITTED,
            JobStatus.IN_PROGRESS,
            JobStatus.FAILED,
        ]:
            if landing_jobs[_status]:
                status = str(_status)
                break

        return JsonResponse({"status": status}, status=200)

    def post(
        self, request: WSGIRequest, repo_name: int, pull_number: int
    ) -> JsonResponse:
        """Create a new landing job for a pull request."""

        class Form(forms.Form):
            """Simple form to get clean some fields."""

            head_sha = forms.CharField()
            # TODO: use this for verification later, see bug 1996571.
            # base_ref = forms.CharField()

        target_repo = Repo.objects.get(name=repo_name)
        client = GitHubAPIClient(target_repo)
        ldap_username = request.user.email
        pull_request = PullRequest(client.get_pull_request(pull_number), target_repo)
        form = Form(json.loads(request.body))

        if not form.is_valid():
            return JsonResponse(form.errors, 400)

        # TODO: this does not work with binary data, must use patch instead.
        # See bug 1993047.
        diff = client.get_diff(pull_number)
        job = LandingJob.objects.create(
            target_repo=target_repo, requester_email=ldap_username
        )
        revision = Revision.objects.create(pull_number=pull_request.number)
        patch_data = {
            # See bug 1995006 (to actually parse authorship info). Use placeholder for now.
            "author_name": "Author Name",
            "author_email": "Author Email <email@example.org>",
            "commit_message": pull_request.title,
            "timestamp": int(datetime.now().timestamp()),
        }
        revision.set_patch(diff, patch_data)
        revision.save()
        add_revisions_to_job([revision], job)
        job.status = JobStatus.SUBMITTED
        job.save()

        return JsonResponse({"id": job.id}, status=201)
