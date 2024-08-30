from __future__ import annotations

import logging
from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.models import Repo, Worker

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
        # Clone or update repos upon worker startup.
        for repo in worker.enabled_repos:
            # Check if any associated repos are unsupported, raise exception if so.
            repo.raise_for_unsupported_repo_scm(repo.HG)
            repo.hg_repo_prepare()

        # Continue with starting the worker.
        try:
            worker = LandingWorker(worker.enabled_repos)
        except ConnectionError as e:
            raise CommandError(e)

        logger.info(f"Starting {worker}...")
        try:
            worker.start()
        finally:
            logger.info(f"{worker} shut down.")

    def handle_git(self, worker: Worker):
        """Handle the starting of the Git landing worker ("git-landing-worker")."""
        raise CommandError("Git landing worker is Not yet implemented")

    def handle(self, name: str, **options):
        """Select a landing worker based on provided argument and start it up."""
        handlers = {
            Repo.HG: self.handle_hg,
            Repo.GIT: self.handle_git,
        }

        worker = self.get_worker(name)
        handlers[worker.scm](worker)
