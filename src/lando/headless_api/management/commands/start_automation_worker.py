import logging

from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)
from lando.workers.automation_worker import AutomationWorker

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start the specified worker."
    worker_class = AutomationWorker
