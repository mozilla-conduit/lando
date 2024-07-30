from __future__ import annotations

import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand
from lando.main.workers.hg_landing_worker import HgLandingWorker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Start the hg landing worker."

    def __init__(self):
        super().__init__()

        call_command("sync_repos")

        self.worker = HgLandingWorker(self.stdout)

    def handle(self, *args, **options):
        self.worker.start()
