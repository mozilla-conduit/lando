from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse

from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models.landing_job import JobStatus, LandingJob
from lando.main.scm.consts import SCM_TYPE_HG
from lando.ui.views import LandoView

TREEHERDER_JOBS = "https://treeherder.mozilla.org/jobs"


class JobView(LandoView):
    pass


class LandingQueueView(JobView):
    def get(self, request: HttpRequest) -> HttpResponse:
        jobs = LandingJob.job_queue_query().all()
        data = [
            {
                "created_at": j.created_at,
                "id": j.id,
                "url": f"{settings.SITE_URL}/landings/{j.id}",
                "repository": j.target_repo.short_name,
                "requester": j.requester_email,
                "revisions": [
                    f"{settings.PHABRICATOR_URL}/D{r.revision_id}" for r in j.revisions
                ],
                "status": j.status,
                "updated_at": j.updated_at,
            }
            for j in jobs
        ]
        return JsonResponse({"jobs": data}, safe=False)


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


class AutomationJobView(JobView):
    def get(self, request: HttpRequest, automation_job_id: int) -> HttpResponse:
        automation_job = AutomationJob.objects.get(id=automation_job_id)

        context = {"job": automation_job}

        return TemplateResponse(
            request=request,
            template="jobs/job.html",
            context=context,
        )
