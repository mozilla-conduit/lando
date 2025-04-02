"""This module contains the abstract repo worker implementation."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from time import sleep
from typing import Optional

from django.conf import settings

from lando.api.legacy.treestatus import TreeStatus
from lando.main.models import Worker as WorkerModel
from lando.version import version

logger = logging.getLogger(__name__)


class Worker:
    """A base class for repository workers."""

    SSH_PRIVATE_KEY_ENV_KEY = "SSH_PRIVATE_KEY"

    ssh_private_key: Optional[str]

    def __str__(self) -> str:
        return f"Worker {self.worker_instance}"

    def __init__(
        self,
        worker_instance: WorkerModel,
        with_ssh: bool = True,
    ):
        self.worker_instance = worker_instance

        # The list of all repos that are enabled for this worker
        self.enabled_repos = self.worker_instance.enabled_repos

        # The list of all repos that have open trees; refreshed when needed via
        # `self.refresh_active_repos`.
        self.active_repos = []

        self.treestatus_client = TreeStatus(url=settings.TREESTATUS_URL)
        self.treestatus_client.session.headers.update(
            {"User-Agent": f"landoapi.treestatus.TreeStatus/{version}"}
        )
        if not self.treestatus_client.ping():
            raise ConnectionError("Could not connect to Treestatus")

        if with_ssh:
            # Fetch ssh private key from the environment. Note that this key should be
            # stored in standard format including all new lines and new line at the end
            # of the file.
            self.ssh_private_key = os.environ.get(self.SSH_PRIVATE_KEY_ENV_KEY)
            if not self.ssh_private_key:
                logger.warning(
                    f"No {self.SSH_PRIVATE_KEY_ENV_KEY} present in environment."
                )

    @staticmethod
    def _setup_ssh(ssh_private_key: str):
        """Add a given private ssh key to ssh agent.

        SSH keys are needed in order to push to repositories that have an ssh
        push path.

        The private key should be passed as it is in the key file, including all
        new line characters and the new line character at the end.

        Args:
            ssh_private_key (str): A string representing the private SSH key file.
        """
        # Set all the correct environment variables
        agent_process = subprocess.run(
            ["ssh-agent", "-s"], capture_output=True, universal_newlines=True
        )

        # This pattern will match keys and values, and ignore everything after the
        # semicolon. For example, the output of `agent_process` is of the form:
        #     SSH_AUTH_SOCK=/tmp/ssh-c850kLXXOS5e/agent.120801; export SSH_AUTH_SOCK;
        #     SSH_AGENT_PID=120802; export SSH_AGENT_PID;
        #     echo Agent pid 120802;
        pattern = re.compile("(.+)=([^;]*)")
        for key, value in pattern.findall(agent_process.stdout):
            logger.info(f"_setup_ssh: setting {key} to {value}")
            os.environ[key] = value

        # Add private SSH key to agent
        # NOTE: ssh-add seems to output everything to stderr, including upon exit 0.
        add_process = subprocess.run(
            ["ssh-add", "-"],
            input=ssh_private_key,
            capture_output=True,
            universal_newlines=True,
        )
        if add_process.returncode != 0:
            raise Exception(add_process.stderr)
        logger.info("Added private SSH key from environment.")

    @property
    def _paused(self) -> bool:
        """Return the value of the pause configuration variable."""
        # When the pause variable is True, the worker is temporarily paused. The worker
        # resumes when the key is reset to False.
        self.worker_instance.refresh_from_db()
        return self.worker_instance.is_paused

    @property
    def _running(self) -> bool:
        """Return the value of the stop configuration variable."""
        # When the stop variable is True, the worker will exit and will not restart,
        # until the value is changed to False.
        self.worker_instance.refresh_from_db()
        return not self.worker_instance.is_stopped

    def _setup(self):
        """Perform various setup actions."""
        if self.ssh_private_key:
            self._setup_ssh(self.ssh_private_key)

    def _start(self, max_loops: int | None = None, *args, **kwargs):
        """Run the main event loop."""
        # NOTE: The worker will exit when max_loops is reached, or when the stop
        # variable is changed to True.
        loops = 0

        while self._running:
            if not bool(loops % 20):
                # Put an info update in the logs every 20 loops.
                logger.info(self)

            if max_loops is not None and loops >= max_loops:
                break
            while self._paused:
                # Wait a set number of seconds before checking paused variable again.
                logger.info(
                    f"Paused, waiting {self.worker_instance.sleep_seconds} seconds..."
                )
                self.throttle(self.worker_instance.sleep_seconds)
            self.loop(*args, **kwargs)
            loops += 1

        logger.info(f"{self} exited after {loops} loops.")

    @property
    def throttle_seconds(self) -> int:
        """The duration to pause for when the worker is being throttled."""
        return self.worker_instance.throttle_seconds

    def throttle(self, seconds: int | None = None):
        """Sleep for a given number of seconds."""
        sleep(seconds if seconds is not None else self.throttle_seconds)

    def refresh_active_repos(self):
        """Refresh the list of repositories based on treestatus."""
        self.active_repos = [
            r for r in self.enabled_repos if self.treestatus_client.is_open(r.tree)
        ]
        logger.info(f"{len(self.active_repos)} enabled repos: {self.active_repos}")

    def start(self, max_loops: int | None = None):
        """Run setup sequence and start the event loop."""
        if self.worker_instance.is_stopped:
            logger.warning(f"Will not start worker {self}.")
            return
        self._setup()
        self._start(max_loops=max_loops)

    def loop(self, *args, **kwargs):
        """The main event loop."""
        raise NotImplementedError()
