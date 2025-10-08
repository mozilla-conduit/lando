from __future__ import annotations

import logging

from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)
from lando.try_api.worker import TryWorker

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start the specified Try worker."
    worker_class = TryWorker
