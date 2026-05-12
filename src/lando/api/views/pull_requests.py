import json
from collections import defaultdict
from datetime import datetime

from django import forms
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.views import View

from lando.api.legacy.commit_message import replace_reviewers
from lando.main.auth import require_authenticated_user
from lando.main.models import (
    JobStatus,
    LandingJob,
    Repo,
    Revision,
    add_revisions_to_job,
)
from lando.main.models.landing_job import get_jobs_for_pull
from lando.utils.github import GitHubAPIClient, PullRequest, PullRequestPatchHelper
from lando.utils.github_checks import (
    ALL_PULL_REQUEST_BLOCKERS,
    ALL_PULL_REQUEST_WARNINGS,
    PullRequestChecks,
)
from lando.utils.landing_checks import LandingChecks


def generate_warnings_and_blockers(
    target_repo: Repo,
    pull_request: PullRequest,
    request: HttpRequest,
    do_escape: bool = True,
) -> dict[str, list[str]]:
    """Run checks on a pull request and return blockers and warnings."""
    # PullRequestPatchHelper.diff doesn't include binary changes.
    # This is not considered an issue for checks at the moment, but may need to be kept in
    # mind for the future.
    patch_helper = PullRequestPatchHelper(pull_request)
    author_email = pull_request.author[1]
    landing_checks = LandingChecks(author_email, target_repo.name)
    blockers = landing_checks.run(
        target_repo.hooks,
        [patch_helper],
    )
    pr_checks = PullRequestChecks(pull_request.client, target_repo, request)
    pr_blockers = [chk.name() for chk in ALL_PULL_REQUEST_BLOCKERS]
    blockers += pr_checks.run(pr_blockers, pull_request)
    pr_warnings = [chk.name() for chk in ALL_PULL_REQUEST_WARNINGS]
    warnings = pr_checks.run(pr_warnings, pull_request)

    if do_escape:
        # Sanitize blockers and warnings as they may be rendered in a page.
        warnings = [escape(warning) for warning in warnings]
        blockers = [escape(blocker) for blocker in blockers]

    return {"warnings": warnings, "blockers": blockers}


class PullRequestAPIView(View):
    """Set various common attributes for views that extend this one."""

    target_repo: Repo
    client: GitHubAPIClient
    pull_request: PullRequest

    def dispatch(
        self, request: WSGIRequest, repo_name: str, pull_number: int, *args, **kwargs
    ) -> JsonResponse:
        self.target_repo = Repo.objects.get(name=repo_name)
        self.client = GitHubAPIClient(self.target_repo.url)
        self.pull_request = self.client.build_pull_request(pull_number)
        return super().dispatch(request, repo_name, pull_number, *args, **kwargs)


class LandingJobPullRequestAPIView(PullRequestAPIView):
    """Handle pull request landing jobs in the API."""

    def get(
        self, request: WSGIRequest, repo_name: int, pull_number: int
    ) -> JsonResponse:
        """Return the status of a pull request based on landing job counts."""

        landing_jobs = get_jobs_for_pull(self.target_repo, pull_number)
        landing_jobs_by_status = defaultdict(list)
        for landing_job in landing_jobs:
            landing_jobs_by_status[landing_job.status].append(landing_job.id)

        status = None
        # Return the first encountered status in this list.
        for _status in [
            JobStatus.LANDED,
            JobStatus.CREATED,
            JobStatus.SUBMITTED,
            JobStatus.IN_PROGRESS,
            JobStatus.FAILED,
        ]:
            if landing_jobs_by_status[_status]:
                status = str(_status).lower()
                break

        return JsonResponse({"status": status}, status=200)

    @method_decorator(require_authenticated_user)
    def post(
        self, request: WSGIRequest, repo_name: int, pull_number: int
    ) -> JsonResponse:
        """Create a new landing job for a pull request."""

        class Form(forms.Form):
            """Simple form to get clean some fields."""

            head_sha = forms.CharField()
            # TODO: use this for verification later, see bug 1996571.
            # base_ref = forms.CharField()

        ldap_username = request.user.email

        blockers = generate_warnings_and_blockers(
            self.target_repo, self.pull_request, request
        )["blockers"]

        if blockers:
            # Pull request has blockers that prevent it from landing.
            return JsonResponse({"errors": blockers}, status=400)

        form = Form(json.loads(request.body))

        if not form.is_valid():
            return JsonResponse(form.errors, 400)

        job = LandingJob.objects.create(
            target_repo=self.target_repo,
            requester_email=ldap_username,
            is_pull_request_job=True,
        )
        author_name, author_email = self.pull_request.author

        reviews_summary = self.pull_request.reviews_summary
        reviewers = [
            u
            for u in reviews_summary
            if reviews_summary.get(u) == self.pull_request.Review.APPROVED
        ]
        approvals = []

        commit_message = replace_reviewers(
            self.pull_request.commit_message, reviewers, approvals
        )

        patch_data = {
            "author_name": author_name,
            "author_email": author_email,
            "commit_message": commit_message,
            "timestamp": int(datetime.now().timestamp()),
        }
        revision = Revision.objects.create(
            pull_number=self.pull_request.number,
            pull_head_sha=self.pull_request.head_sha,
            pull_base_sha=self.pull_request.base_sha,
            patches=self.pull_request.patch,
            patch_data=patch_data,
        )
        add_revisions_to_job([revision], job)
        job.status = JobStatus.SUBMITTED
        job.save()

        return JsonResponse({"id": job.id}, status=201)


class ChecksPullRequestAPIView(PullRequestAPIView):
    def get(
        self, request: WSGIRequest, repo_name: str, pull_number: int
    ) -> JsonResponse:
        try:
            warnings_and_blockers = generate_warnings_and_blockers(
                self.target_repo, self.pull_request, request
            )
        except PullRequest.StaleMetadataException as exc:
            # The StaleMetadataException error message is safe for user consumption.
            return JsonResponse({"errors": [str(exc)]}, status=500)
        return JsonResponse(warnings_and_blockers)
