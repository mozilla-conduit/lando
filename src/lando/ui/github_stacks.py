import logging

from django.core.handlers.wsgi import WSGIRequest
from django.http import Http404
from django.template.response import TemplateResponse
from requests import HTTPError

from lando.main.auth import PrivateRepoPermissionMixin
from lando.main.models import Repo
from lando.main.models.landing_job import (
    get_jobs_for_pull,
)
from lando.ui.views import LandoView
from lando.utils.github import PR_DELIMITER, GitHubAPIClient

logger = logging.getLogger(__name__)


class StackView(LandoView, PrivateRepoPermissionMixin):
    """A class-based view to handle stacks in the Lando UI."""

    def get(
        self, request: WSGIRequest, repo_name: str, stack_number: int, *args, **kwargs
    ) -> TemplateResponse:
        """Handle the GET request for the stack view."""

        try:
            target_repo = Repo.objects.get(name=repo_name)
        except Repo.DoesNotExist:
            raise Http404()

        if not target_repo.pr_enabled:
            raise Http404()

        client = GitHubAPIClient(target_repo.url)

        self.raise_404_if_needed(request, client)
        try:
            stack = client.build_stack(stack_number)
        except HTTPError as e:
            if e.response.status_code == 404:
                raise Http404() from e
            raise e
        landing_jobs = [
            job
            for pull_request in stack.pull_requests
            for job in get_jobs_for_pull(target_repo, pull_request.number)
        ]

        context = {
            "target_repo": target_repo,
            "stack": stack,
            "landing_jobs": landing_jobs,
            "pr_delimiter": PR_DELIMITER,
        }

        return TemplateResponse(
            request=request,
            template="stack/github_stack.html",
            context=context,
        )
