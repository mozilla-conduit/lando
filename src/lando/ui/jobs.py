from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse

from lando.api.legacy.treestatus import (
    TreeStatusCommunicationException,
    TreeStatusError,
)
from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models.landing_job import JobStatus, LandingJob
from lando.main.models.worker import Worker, WorkerType
from lando.main.scm import SCM_TYPE_HG
from lando.ui.views import LandoView
from lando.utils import treestatus


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

        ts_data = {"repo": landing_job.target_repo.short_name}

        ts_client = treestatus.getTreestatusClient()
        try:
            ts_data.update(ts_client.get_trees(ts_data["repo"])["result"])
        except (TreeStatusCommunicationException, TreeStatusError) as exc:
            ts_data.update({"status": "unknown", "reason": exc})

        context = {
            "job": landing_job,
            "treestatus": ts_data,
        }

        if landing_job.status not in JobStatus.final():
            # There's only one Landing worker for each repo.

            try:
                landing_worker = Worker.objects.get(
                    applicable_repos=landing_job.target_repo, type=WorkerType.LANDING
                )
            except Worker.DoesNotExist:
                queue = []
            else:
                queue_query = LandingJob.job_queue_query(
                    repositories=landing_worker.applicable_repos.all(),
                    # We set the grace_seconds to 0, so all current jobs are shown, including
                    # those in the grace period, so they don't appear unannounced later.
                    grace_seconds=0,
                )
                queue = list(queue_query.all())
                # Only include jobs before the current landing_job in the queue
                # I'd rather do this DB-side, but I couldn't work out how.
                if landing_job in queue:
                    queue = queue[: queue.index(landing_job)]
            context["queue"] = queue
        else:
            # XXX: Only works for Hg repos, waiting for bug 1963822.
            if landing_job.target_repo.scm_type == SCM_TYPE_HG:
                context["treeherder"] = {
                    "job_url": f"{settings.TREEHERDER_URL}/jobs?revision={landing_job.landed_commit_id}"
                }

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
