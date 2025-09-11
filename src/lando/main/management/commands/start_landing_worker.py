from __future__ import annotations

import logging

from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start the specified landing worker."
    worker_class = LandingWorker
