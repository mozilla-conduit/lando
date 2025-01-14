from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from io import StringIO

from django.core.management.base import BaseCommand
from django.db import transaction

from lando.main.management.commands import WorkerMixin
from lando.main.models.landing_job import LandingJob, LandingJobStatus
from lando.main.models.repo import Repo

logger = logging.getLogger(__name__)


@contextmanager
def job_processing(job: LandingJob):
    """Mutex-like context manager that manages job processing miscellany.

    This context manager facilitates graceful worker shutdown, tracks the duration of
    the current job, and commits changes to the DB at the very end.

    Args:
        job: the job currently being processed
        db: active database session
    """
    start_time = datetime.now()
    try:
        yield
    finally:
        job.duration_seconds = (datetime.now() - start_time).seconds


# TODO what is this? should it be removed?
class Command(BaseCommand, WorkerMixin):
    help = "Start the landing worker."
    name = "landing-worker"

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        self.last_job_finished = None
        self.start()

    def loop(self):
        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self._instance.sleep_seconds)

        for repo in self._instance.enabled_repos:
            if not repo.is_initialized:
                repo.initialize()

        with transaction.atomic():
            job = LandingJob.next_job(repositories=self._instance.enabled_repos).first()

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
