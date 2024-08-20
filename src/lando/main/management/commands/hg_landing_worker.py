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
        try:
            worker = LandingWorker(self._instance.enabled_repos)
        except ConnectionError as e:
            raise CommandError(e)

        worker.start()
