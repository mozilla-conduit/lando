import logging

from lando.api.legacy.workers.automation_worker import AutomationWorker
from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start the specified worker."
    worker_class = AutomationWorker
