from __future__ import annotations

import logging
from io import StringIO

from django.db import transaction
from lando.main.models.base import Repo
from lando.main.models.landing_job import LandingJob, LandingJobStatus
from lando.main.workers.base_worker import BaseWorker, job_processing

logger = logging.getLogger(__name__)


class GitLandingWorker(BaseWorker):
    @property
    def name(self):
        return "git-landing-worker"

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **kwargs):
        self.start(*args, **kwargs)

    def loop(self, *args, **kwargs):
        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self._instance.sleep_seconds)

        for repo in self._instance.enabled_repos:
            if not repo.is_initialized:
                repo.initialize()

        with transaction.atomic():
            repository_names = [repo.name for repo in self._instance.enabled_repos]
            job = LandingJob.next_job(repository_names=repository_names).first()

            if job is None:
                self.throttle(self._instance.sleep_seconds)
                return

            with job_processing(job):
                job.status = LandingJobStatus.IN_PROGRESS
                job.attempts += 1
                job.save()

                self.stdout.write(f"Starting landing job {job}")
                self.last_job_finished = self.run_job(job)
                self.stdout.write("Finished processing landing job")

    def run_job(self, job: LandingJob) -> bool:
        repo = job.target_repo
        if not repo:
            repo = Repo.objects.get(name=job.repository_name)
        repo.reset()
        repo.pull()

        for revision in job.revisions.all():
            patch_buffer = StringIO(revision.patch)
            repo.apply_patch(patch_buffer)

            # TODO: need to account for reverts/backouts somehow in the futue.
            revision.commit_id = repo._run("rev-parse", "HEAD").stdout.strip()
            revision.save()

            repo.push()

        job.status = LandingJobStatus.LANDED
        job.save()

        return True
