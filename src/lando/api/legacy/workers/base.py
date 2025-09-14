"""This module contains the abstract repo worker implementation."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from abc import ABC, abstractmethod
from time import sleep

from celery import Task
from django.db import transaction
from kombu.exceptions import OperationalError

import lando.utils.treestatus
from lando.api.legacy.treestatus import TreeStatus
from lando.main.models import (
    BaseJob,
    JobStatus,
    Repo,
    WorkerType,
)
from lando.main.models import Worker as WorkerModel
from lando.main.models.jobs import (
    JobAction,
    PermanentFailureException,
    TemporaryFailureException,
)
from lando.main.models.revision import Revision
from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.exceptions import (
    NoDiffStartLine,
    PatchConflict,
    SCMInternalServerError,
)

logger = logging.getLogger(__name__)


class Worker(ABC):
    """A base class for repository workers."""

    SSH_PRIVATE_KEY_ENV_KEY = "SSH_PRIVATE_KEY"

    # Type of Job that this worker can process.
    job_type: type[BaseJob]

    # Type of the Worker implementation.
    worker_type: WorkerType

    worker_instance: WorkerModel

    @abstractmethod
    def run_job(self, job: BaseJob) -> bool:
        """Process a job as needed.

        Implementors may raise TemporaryFailureException or PermanentFailureException to
        use the basic error handling, or use a more specific approach as needed.

        Returns:
            bool: Whether the job succeeded.
        """

    def bootstrap_repos(self):
        """Optional method to bootstrap repositories in the the work directory."""
        return

    ssh_private_key: str | None

    treestatus_client: TreeStatus

    # The list of all repos that have open trees; refreshed when needed via
    # `self.refresh_active_repos`.
    active_repos: list[Repo]

    last_job_finished: bool | None = None

    def __str__(self) -> str:
        return f"{self.__class__.__name__} {self.worker_instance}"

    def __init__(
        self,
        worker_instance: WorkerModel,
        with_ssh: bool = True,
    ):
        self.worker_instance = worker_instance

        self.treestatus_client = lando.utils.treestatus.get_treestatus_client()
        if not self.treestatus_client.ping():
            raise ConnectionError("Could not connect to Treestatus")

        self.refresh_active_repos()

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

    def loop(self):
        """Fetch jobs and processes them.

        Jobs are found using the first entity from the `job_type.next_job()` method.
        They are then processed through the concrete implementation's `run_job()`.

        Basic error-handling and job-status management is performed for temporary,
        permanent, and unexpected exceptions not handled by the concrete implementation's
        `run_job()`.
        """
        logger.debug(f"{len(self.enabled_repos)} enabled repos: {self.enabled_repos}")

        # Refresh repos if there is a mismatch in active vs. enabled repos.
        if len(self.active_repos) != len(self.enabled_repos):
            self.refresh_active_repos()

        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self.worker_instance.sleep_seconds)
            # We refresh again after a throttle, in case trees were closed or re-opened.
            self.refresh_active_repos()

        with transaction.atomic():
            job = self.job_type.next_job(repositories=self.active_repos).first()

        if job is None:
            self.throttle(self.worker_instance.sleep_seconds)
            return

        with job.processing():
            logger.info(f"Starting {job}", extra={"id": job.id})

            if job.status not in [JobStatus.SUBMITTED, JobStatus.DEFERRED]:
                logger.warning(f"Unexpected status for {job}")

            job.status = JobStatus.IN_PROGRESS
            job.attempts += 1
            # Make sure the status and attempt count are updated in the database
            job.save()

            try:
                self.last_job_finished = self.run_job(job)
            except TemporaryFailureException as exc:
                job.transition_status(JobAction.DEFER, message=str(exc))
                self.last_job_finished = False
                logger.warning(
                    f"Temporary failure for {job}: {exc}",
                    extra={"id": job.id},
                )
            except PermanentFailureException as exc:
                job.transition_status(JobAction.FAIL, message=str(exc))
                self.last_job_finished = False
                logger.warning(
                    f"Permanent failure for {job}: {exc}",
                    extra={"id": job.id},
                )
            except Exception:
                job.transition_status(
                    JobAction.FAIL,
                    message=(
                        "An unexpected error occurred. This has been logged. Feel free to follow up on matrix #conduit:mozilla.org."
                    ),
                )
                self.last_job_finished = False
                # This will report the exception to Sentry.
                logger.exception(
                    f"Unhandled exception for {job}",
                    extra={"id": job.id},
                )
            else:
                logger.info(
                    f"Finished processing {job}",
                    extra={"id": job.id},
                )

    @property
    def throttle_seconds(self) -> int:
        """The duration to pause for when the worker is being throttled."""
        return self.worker_instance.throttle_seconds

    def throttle(self, seconds: int | None = None):
        """Sleep for a given number of seconds."""
        sleep(seconds if seconds is not None else self.throttle_seconds)

    @property
    def enabled_repos(self) -> list[Repo]:
        """The list of all repos that are enabled for this worker."""
        return self.worker_instance.enabled_repos

    def refresh_active_repos(self):
        """Refresh the list of repositories based on treestatus."""
        self.active_repos = [
            r for r in self.enabled_repos if self.treestatus_client.is_open(r.tree)
        ]
        logger.info(f"{len(self.active_repos)} enabled repos: {self.active_repos}")

    def update_repo(
        self, repo: Repo, job: BaseJob, scm: AbstractSCM, target_cset: str | None
    ) -> str:
        """Update repository with job status handling."""
        repo_pull_info = f"tree: {repo.tree}, pull path: {repo.pull_path}"
        try:
            return scm.update_repo(
                repo.pull_path,
                target_cset=target_cset,
                attributes_override=repo.attributes_override,
            )
        except SCMInternalServerError as e:
            message = (
                f"`Temporary error ({e.__class__}) "
                f"encountered while pulling from {repo_pull_info}: {e}"
            )
            logger.exception(message)
            job.transition_status(JobAction.DEFER, message=message)

            # Try again, this is a temporary failure.
            raise TemporaryFailureException(message) from e
        except Exception as e:
            message = f"Unexpected error while fetching repo from {repo.name}."
            logger.exception(message)
            job.transition_status(
                JobAction.FAIL,
                message=message + f"\n{e}",
            )
            raise PermanentFailureException(message) from e

    def apply_patch(
        self,
        repo: Repo,
        job: BaseJob,
        scm: AbstractSCM,
        revision: Revision,
    ) -> None:
        """Apply patches to repo with job status handling."""
        try:
            scm.apply_patch(
                revision.diff,
                revision.commit_message,
                revision.author,
                revision.timestamp,
            )
        except NoDiffStartLine as exc:
            message = (
                "Lando encountered a malformed patch, please try again. "
                "If this error persists please file a bug: "
                "Patch without a diff start line."
            )
            logger.error(message)
            job.transition_status(
                JobAction.FAIL,
                message=message,
            )
            raise PermanentFailureException(message) from exc

        except PatchConflict as exc:
            breakdown = scm.process_merge_conflict(
                repo.normalized_url, revision.revision_id, str(exc)
            )
            job.error_breakdown = breakdown

            message = (
                f"Problem while applying patch in revision {revision.revision_id}:\n\n"
                f"{str(exc)}"
            )
            logger.exception(message)
            job.transition_status(JobAction.FAIL, message=message)
            raise PermanentFailureException(message) from exc
        except Exception as exc:
            message = (
                f"Aborting, could not apply patch buffer for {revision.revision_id}."
                f"\n{exc}"
            )
            logger.exception(message)
            job.transition_status(
                JobAction.FAIL,
                message=message,
            )
            raise PermanentFailureException(message) from exc

    def start(self, max_loops: int | None = None):
        """Run setup sequence and start the event loop."""
        if self.worker_instance.is_stopped:
            logger.warning(f"Will not start worker {self}.")
            return
        self._setup()
        self._start(max_loops=max_loops)

    @staticmethod
    def call_task(task: Task, *args):
        """Exception-absorbing wrapper to call asynchronous Celery tasks.

        Args:
            task: celery.Task to call
            *args: list of argurents for the Task
        """
        try:
            # Send a task to Celery.
            task.apply_async(args=args)
        except OperationalError as e:
            # Log the exception but continue gracefully.
            logger.exception(f"Failed sending {task.__name__} task to Celery.")
            logger.exception(e)
