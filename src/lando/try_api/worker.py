from typing_extensions import override

from lando.api.legacy.workers.base import Worker
from lando.main.models import (
    WorkerType,
)
from lando.try_api.models.job import TryJob


class TryWorker(Worker):
    job_type = TryJob
    worker_type = WorkerType.TRY

    @override
    def run_job(self, job: TryJob) -> bool:
        raise NotImplementedError()
