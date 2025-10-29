import logging

from django.core.handlers.wsgi import WSGIRequest
from django.template.response import TemplateResponse

from lando.main.models import Repo
from lando.main.models.landing_job import get_jobs_for_pull
from lando.ui.views import LandoView
from lando.utils.github import GitHubAPIClient

logger = logging.getLogger(__name__)


class PullRequestView(LandoView):
    """A class-based view to handle pull requests in the Lando UI."""

    def get(
        self, request: WSGIRequest, repo_name: str, number: int, *args, **kwargs
    ) -> TemplateResponse:
        """Handle the GET request for the pull request view."""
        target_repo = Repo.objects.get(name=repo_name)
        client = GitHubAPIClient(target_repo)
        pull_request = client.build_pull_request(number)
        landing_jobs = get_jobs_for_pull(target_repo, number)

        context = {
            "target_repo": target_repo,
            "pull_request": pull_request,
            "landing_jobs": landing_jobs,
        }

        return TemplateResponse(
            request=request,
            template="stack/pull_request.html",
            context=context,
        )
