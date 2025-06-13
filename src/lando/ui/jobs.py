from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse

from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models.landing_job import LandingJob
from lando.ui.views import LandoView

TREEHERDER_JOBS = "https://treeherder.mozilla.org/jobs"


class JobView(LandoView):
    pass


class LandingJobView(JobView):
    def get(
        self, request: HttpRequest, landing_job_id: int, revision_id: None | int
    ) -> HttpResponse:
        landing_job = get_object_or_404(LandingJob, id=landing_job_id)

        # Redirect to the canonical URL in case the revision is missing or
        # incorrect.
        if not revision_id or (
            not landing_job.revisions.filter(revision_id=revision_id)
        ):
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
