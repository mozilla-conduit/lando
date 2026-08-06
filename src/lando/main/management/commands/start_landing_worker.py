import logging

from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)
from lando.workers.landing_worker import LandingWorker

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start the specified landing worker."
    worker_class = LandingWorker
