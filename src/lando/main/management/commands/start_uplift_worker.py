from __future__ import annotations

import logging

from lando.api.legacy.workers.uplift_worker import UpliftWorker
from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start an uplift worker."
    worker_class = UpliftWorker
