from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from time import sleep

from lando.main.models.landing_job import LandingJob
from lando.main.models.repo import Worker


@contextmanager
def job_processing(job: LandingJob):
    """Mutex-like context manager that manages job processing miscellany.

    This context manager facilitates graceful worker shutdown, tracks the duration of
    the current job, and commits changes to the DB at the very end.

    Args:
        job: the job currently being processed
        db: active database session
    """
    start_time = datetime.now()
    try:
        yield
    finally:
        job.duration_seconds = (datetime.now() - start_time).seconds


class BaseWorker(ABC):

    def __init__(self, stdout, *args, **kwargs):
        self.stdout = stdout
        self.last_job_finished = None

    @property
    @abstractmethod
    def name(self):
        pass

    @property
    def _instance(self) -> Worker:
        return Worker.objects.get(name=self.name)

    @abstractmethod
    def loop(self, *args, **kwargs):
        pass

    @abstractmethod
    def _setup(self):
        pass

    def throttle(self, seconds: int | None = None):
        """Sleep for a given number of seconds."""
        sleep(seconds if seconds is not None else self._instance.throttle_seconds)

    def start(self, max_loops: int | None = None, *args, **kwargs):
        """Run setup sequence and start the event loop."""
        if self._instance.is_stopped:
            return

        self._setup()

        # NOTE: The worker will exit when max_loops is reached, or when the stop
        # variable is changed to True.
        loops = 0
        while not self._instance.is_stopped:
            if max_loops is not None and loops >= max_loops:
                break
            while self._instance.is_paused:
                self.throttle(self._instance.sleep_seconds)
            self.loop(*args, **kwargs)
            loops += 1

        self.stdout.write(f"{self} exited after {loops} loops.")
