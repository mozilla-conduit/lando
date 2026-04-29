import logging
from abc import ABC

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse

from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models import JobStatus, LandingJob, Worker, WorkerType
from lando.main.models.jobs import BaseJob
from lando.main.models.uplift import UpliftJob
from lando.ui.views import LandoView
from lando.utils import treestatus

logger = logging.getLogger(__name__)  # noqa: F821


class BaseJobView(LandoView, ABC):
    # Type of Job that this view can show.
    job_type: type[BaseJob]

    # Type of the Worker implementation (for accurate queue display).
    worker_type: WorkerType

    def get(self, request: WSGIRequest, job_id: int) -> TemplateResponse:
        job = self.job_type.objects.get(id=job_id)

        context = {"job": job}

        if job.status not in JobStatus.final():
            context["queue"] = self.worker_queue(job)

        return TemplateResponse(
            request=request,
            template="jobs/job.html",
            context=context,
        )

    # XXX: this should be on the worker
    def worker_queue(self, job: BaseJob, **kwargs) -> list[BaseJob]:
        """
        Return a list of the jobs ahead of the passed job for the associated worker.

        This relies on `self.worker_type` to find the associated worker, and
        `self.job_type` to find the jobs of the same type.

        Parameters:

        job: BaseJob
            the job to look up in the queue

        **kwargs (dict): Additional arguments for the queue query

        Returns:
            list[BaseJob]: an ordered list of the jobs ahead
        """
        try:
            worker = Worker.objects.get(
                applicable_repos=job.target_repo,
                type=self.worker_type,
            )
        except Worker.DoesNotExist:
            return []

        queue_query = self.job_type.job_queue_query(
            repositories=worker.applicable_repos.all(),
            **kwargs,
        )
        queue = list(queue_query.all())
        # Only include jobs before the current landing_job in the queue
        # I'd rather do this DB-side, but I couldn't work out how.
        if job in queue:
            queue = queue[: queue.index(job)]

        return queue


class LandingJobView(BaseJobView):
    job_type = LandingJob
    worker_type = WorkerType.LANDING

    def get(
        self, request: WSGIRequest, job_id: int, revision_id: int | None
    ) -> TemplateResponse | HttpResponsePermanentRedirect | HttpResponseRedirect:
        landing_job = get_object_or_404(LandingJob, id=job_id)

        # Redirect to the canonical URL in case the revision is missing or
        # incorrect.
        if (
            not revision_id
            or (not landing_job.revisions.filter(revision_id=revision_id))
        ) and (revision_id := landing_job.revisions[0].revision_id):
            return redirect(
                "revision-jobs-page",
                job_id=job_id,
                revision_id=revision_id,
            )

        context = {
            "job": landing_job,
            "treestatus": treestatus.get_treestatus_data(
                landing_job.target_repo.short_name
            ),
        }

        if landing_job.status not in JobStatus.final():
            # There's only one Landing worker for each repo.

            # We set the grace_seconds to 0, so all current jobs are shown, including
            # those in the grace period, so they don't appear unannounced later.
            context["queue"] = self.worker_queue(landing_job, grace_seconds=0)

        return TemplateResponse(
            request=request,
            template="jobs/job.html",
            context=context,
        )


class AutomationJobView(BaseJobView):
    job_type = AutomationJob
    worker_type = WorkerType.AUTOMATION


class UpliftJobView(BaseJobView):
    job_type = UpliftJob
    worker_type = WorkerType.UPLIFT
