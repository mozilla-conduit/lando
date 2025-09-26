import logging

from django.core.handlers.wsgi import WSGIRequest
from django.template.response import TemplateResponse

from lando.main.models import Repo
from lando.ui.views import LandoView
from lando.utils.github import GitHubAPIClient, PullRequest

logger = logging.getLogger(__name__)


class PullRequestView(LandoView):
    def get(
        self, request: WSGIRequest, repo_name: str, number: int, *args, **kwargs
    ) -> TemplateResponse:
        target_repo = Repo.objects.get(name=repo_name)
        client = GitHubAPIClient(target_repo)
        pull_request = PullRequest(client.get_pull_request(number))

        context = {
            "dryrun": None,
            "target_repo": target_repo,
            "pull_request": pull_request,
        }

        return TemplateResponse(
            request=request,
            template="stack/pull_request.html",
            context=context,
        )
