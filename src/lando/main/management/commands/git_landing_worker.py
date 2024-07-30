from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from lando.main.workers.git_landing_worker import GitLandingWorker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Start the git landing worker."

    def __init__(self):
        super().__init__()

        self.worker = GitLandingWorker(stdout=self.stdout)

    def handle(self, *args, **options):
        self.worker.start()
