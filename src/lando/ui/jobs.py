from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from lando.main.models.landing_job import LandingJob
from lando.ui.views import LandoView

TREEHERDER_JOBS = "https://treeherder.mozilla.org/jobs"


class JobView(LandoView):
    pass


class LandingJobView(JobView):
    def get(
        self, request: HttpRequest, landing_job_id: int, revision_id: None | int
    ) -> HttpResponse:
        # XXX: if not found, offer a redirection to Try
        landing_job = LandingJob.objects.get(id=landing_job_id)

        if not revision_id or (
            not landing_job.revisions.filter(revision_id=revision_id)
        ):
            # Redirect to the canonical URL.
            revision_id = landing_job.revisions[0].revision_id
            return redirect(
                "revision-jobs-page",
                landing_job_id=landing_job_id,
                revision_id=revision_id,
            )

        context = {"job": landing_job}

        return TemplateResponse(
            request=request,
            template="jobs/job.html",
            context=context,
        )
