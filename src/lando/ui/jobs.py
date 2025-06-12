import urllib

import requests
from django.http import HttpResponse, HttpRequest
from django.template.response import TemplateResponse

from lando.ui.views import LandoView

TREEHERDER_JOBS = "https://treeherder.mozilla.org/jobs"


class JobView(LandoView):
    pass


class Job(JobView):
    pass


class LandingJob(JobView):
    def get(self, request: HttpRequest, landing_job_id: int) -> HttpResponse:
        # XXX: if not found, offer a redirection to Try
        landing_job = LandingJob.objects.get(id=landing_job_id)

        return HttpResponse(landing_job.id)


class LegacyTryJob(JobView):
    LANDO_API_BASE_URL = "https://api.lando.services.mozilla.com"
    LANDO_API_LANDING_JOBS_ENDPOINT = "landing_jobs"

    def get(self, request: HttpRequest, landing_job_id: int) -> HttpResponse:
        repo = "try"

        landing_job_url = f"{self.LANDO_API_BASE_URL}/{self.LANDO_API_LANDING_JOBS_ENDPOINT}/{landing_job_id}"
        # Placeholder for GET method implementation

        context = {
            "landing_job_id": landing_job_id,
            "landing_job_url": landing_job_url,
        }

        job_state = requests.get(landing_job_url)
        if job_state.status_code >= 400:
            title = "Error"
            detail = "An unknown error happened"
            if "application/problem+json" in job_state.headers.get("content-type", ""):
                error_state = job_state.json()
                title = error_state.get("title", title)
                detail = error_state.get("detail", detail)

            return HttpResponse(
                f'<h1>{title}</h1><a href="{landing_job_url}">{landing_job_url}</a><p>{detail}'
            )

        # {
        #   "commit_id": "de2e9275c82ff58b33626842d93c0c605cd3f98b",
        #   "id": 136624,
        #   "status": "IN_PROGRESS"
        # }
        job_data = job_state.json()
        revision = job_data.get("commit_id")

        context["job_data"] = job_data

        treeherder_params = {
            "repo": repo,
            "landoCommitId": landing_job_id,
            # "revision": revision,
        }
        treeherder_url = f"{TREEHERDER_JOBS}?" + urllib.parse.urlencode(
            treeherder_params
        )

        context["treeherder_url"] = treeherder_url

        return TemplateResponse(
            request=request,
            template="jobs/job.html",
            context=context,
        )
