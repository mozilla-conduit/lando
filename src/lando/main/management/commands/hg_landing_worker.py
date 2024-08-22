from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.management.commands import WorkerMixin

logger = logging.getLogger(__name__)


class Command(BaseCommand, WorkerMixin):
    help = "Start the Mercurial landing worker."
    name = "hg-landing-worker"

    def handle(self, *args, **options):
        # Clone or update repos upon worker startup.
        for repo in self._instance.enabled_repos:
            # Check if any associated repos are unsupported, raise exception if so.
            repo.raise_if_not(repo.HG)
            repo.hg_repo_prepare()

        # Continue with starting the worker.
        try:
            worker = LandingWorker(self._instance.enabled_repos)
        except ConnectionError as e:
            raise CommandError(e)

        worker.start()
