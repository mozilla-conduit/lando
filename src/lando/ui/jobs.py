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


            )


        return TemplateResponse(
            request=request,
            template="jobs/job.html",
            context=context,
        )
