from __future__ import annotations

import logging
from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.models import Worker
from lando.main.scm import SCM_GIT, SCM_HG

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Start a specified landing worker."

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
        """Handle the starting of the Mercurial landing worker ("hg-landing-worker")."""
        self._handle(worker, SCM_HG)

    def handle_git(self, worker: Worker):
        """Handle the starting of the Git landing worker ("git-landing-worker")."""
        self._handle(worker, SCM_GIT)

    def _handle(self, worker: Worker, repo_type: str):
        # Clone or update repos upon worker startup.
        repos_to_handle = []
        for repo in worker.enabled_repos:
            # Check if any associated repos are unsupported, raise exception if so.
            repo.raise_for_unsupported_repo_scm(repo_type)
            scm = repo.get_scm()
            try:
                scm.prepare_repo(repo.pull_path)
            except Exception as e:
                logger.warning(
                    "Fail to prepare repo, skipping...",
                    extra={
                        "exception": e,
                        "origin": repo.pull_path,
                        "scm": scm.scm_type,
                    },
                )
            else:
                repos_to_handle.append(repo)

        # Continue with starting the worker.
        try:
            landing_worker = LandingWorker(repos_to_handle)
        except ConnectionError as e:
            raise CommandError(e)

        logger.info(f"Starting {worker}...")
        try:
            landing_worker.start()
        finally:
            logger.info(f"{worker} shut down.")

    def handle(self, name: str, **options):
        """Select a landing worker based on provided argument and start it up."""
        handlers = {
            SCM_HG: self.handle_hg,
            SCM_GIT: self.handle_git,
        }

        worker = self.get_worker(name)
        handlers[worker.scm](worker)
