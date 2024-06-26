from time import sleep

from lando.main.models.base import Worker


class WorkerMixin:
    @property
    def _instance(self) -> Worker:
        return Worker.objects.get(name=self.name)

    def _start(self, max_loops: int | None = None, *args, **kwargs):
        """Run the main event loop."""
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

    def throttle(self, seconds: int | None = None):
        """Sleep for a given number of seconds."""
        sleep(seconds if seconds is not None else self._instance.throttle_seconds)

    def start(self, max_loops: int | None = None):
        """Run setup sequence and start the event loop."""
        if not self._instance.is_stopped:
            self._start(max_loops=max_loops)

    def loop(self, *args, **kwargs):
        """The main event loop."""
        raise NotImplementedError()
