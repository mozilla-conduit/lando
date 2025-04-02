from __future__ import annotations

import logging
from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from lando.api.legacy.workers.automation_worker import AutomationWorker
from lando.main.models import Worker
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Start the automation worker."

    def get_worker(self, worker_name: str) -> Worker:
        """Return the Worker instance corresponding to the requested worker."""
        try:
            worker = Worker.objects.get(name=worker_name)
        except Worker.DoesNotExist as e:
            raise CommandError(f"{worker_name}: {e}")
        return worker

    def add_arguments(self, parser: ArgumentParser) -> None:
        WORKER_NAMES = Worker.objects.all().values_list("name", flat=True)
        parser.add_argument(
            "name",
            nargs="?",
            default="hg",
            help=f"Enter one of {', '.join(WORKER_NAMES)}",
        )

    def handle_hg(self, worker: Worker):
        """Handle the starting of the Mercurial automation worker ("hg-automation-worker")."""
        self._handle(worker, SCM_TYPE_HG)

    def handle_git(self, worker: Worker):
        """Handle the starting of the Git automation worker ("git-automation-worker")."""
        self._handle(worker, SCM_TYPE_GIT)

    def _check_for_unsupported_repos(self, worker: Worker, repo_type: str):
        for repo in worker.enabled_repos:
            # Check if any associated repos are unsupported, raise exception if so.
            repo.raise_for_unsupported_repo_scm(repo_type)

    def _prepare_repos(self, worker: Worker):
        for repo in worker.enabled_repos:
            if not repo.scm.repo_is_initialized:
                logger.info(f"Repo {repo} not prepared, preparing...")
                repo.scm.prepare_repo(repo.pull_path)

    def _handle(self, worker: Worker, repo_type: str):
        self._check_for_unsupported_repos(worker, repo_type)
        max_attempts = 5
        all_repos_cloned = False
        for attempt in range(max_attempts):
            logger.info(f"Attempting to prepare repos (attempt #{attempt}).")
            try:
                self._prepare_repos(worker)
            except Exception as e:
                logger.error("Encountered error while preparing repos.")
                logger.exception(e)
                continue
            else:
                all_repos_cloned = True
                break

        if not all_repos_cloned:
            raise CommandError(
                "Could not prepare all repos. Check logs for more details."
            )

        # Continue with starting the worker.
        try:
            automation_worker = AutomationWorker(worker)
        except ConnectionError as e:
            raise CommandError(e)

        logger.info(f"Starting {worker}...")
        try:
            automation_worker.start()
        finally:
            logger.info(f"{worker} shut down.")

    def handle(self, name: str, **options):
        """Select an automation worker based on provided argument and start it up."""
        handlers = {
            SCM_TYPE_GIT: self.handle_git,
            SCM_TYPE_HG: self.handle_hg,
        }

        worker = self.get_worker(name)
        handlers[worker.scm](worker)
