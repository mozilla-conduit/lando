from typing_extensions import override

from lando.api.legacy.workers.base import Worker
from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models import (
    BaseJob,
    WorkerType,
)


class TryWorker(Worker):
    job_type = AutomationJob
    worker_type = WorkerType.TRY

    @override
    def run_job(self, job: BaseJob) -> bool:
        raise NotImplementedError()
