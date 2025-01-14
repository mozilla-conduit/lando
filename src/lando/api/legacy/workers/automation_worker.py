import logging
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from typing import Any

import kombu
from django.db import transaction

from lando.api.legacy.hgexports import HgPatchHelper
from lando.api.legacy.notifications import (
    notify_user_of_landing_failure,
)
from lando.api.legacy.workers.base import Worker
from lando.main.api import (
    Action,
    AddBranchAction,
    AddCommitAction,
    MergeOntoAction,
    TagAction,
)
from lando.main.models.automation_job import (
    AutomationJob,
)
from lando.main.models.configuration import ConfigurationKey
from lando.main.models.landing_job import LandingJobAction, LandingJobStatus
from lando.main.models.repo import Repo
from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.exceptions import (
    PatchConflict,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.utils.tasks import phab_trigger_repo_update

logger = logging.getLogger(__name__)


def map_to_pydantic_action(action_type: str, action_data: dict[str, Any]) -> Action:
    """Convert a dict to an `Action` object.

    TODO there must be a better way to do this?
    """
    return {
        "add-commit": AddCommitAction,
        "merge-onto": MergeOntoAction,
        "tag": TagAction,
        "add-branch": AddBranchAction,
    }[action_type](**action_data)


@contextmanager
def job_processing(job: AutomationJob):
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


class AutomationWorker(Worker):
    """Worker to land headless API patches."""

    @property
    def STOP_KEY(self) -> ConfigurationKey:
        """Return the configuration key that prevents the worker from starting."""
        return ConfigurationKey.AUTOMATION_WORKER_STOPPED

    @property
    def PAUSE_KEY(self) -> ConfigurationKey:
        """Return the configuration key that pauses the worker."""
        return ConfigurationKey.AUTOMATION_WORKER_PAUSED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_job_finished = None
        self.refresh_enabled_repos()

    def loop(self):
        logger.debug(
            f"{len(self.applicable_repos)} applicable repos: {self.applicable_repos}"
        )

        # Check if any closed trees reopened since the beginning of this iteration
        if len(self.enabled_repos) != len(self.applicable_repos):
            self.refresh_enabled_repos()

        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self.sleep_seconds)
            self.refresh_enabled_repos()

        with transaction.atomic():
            job = AutomationJob.next_job(repositories=self.enabled_repos).first()

        if job is None:
            self.throttle(self.sleep_seconds)
            return

        with job_processing(job):
            job.status = LandingJobStatus.IN_PROGRESS
            job.attempts += 1
            job.save()

            # Make sure the status and attempt count are updated in the database
            logger.info("Starting landing job", extra={"id": job.id})
            self.last_job_finished = self.run_automation_job(job)
            logger.info("Finished processing landing job", extra={"id": job.id})

    def add_commit_action(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, action: AddCommitAction
    ) -> bool:
        """Run the `add-commit` action."""
        patch_helper = HgPatchHelper(StringIO(action.content))

        date = patch_helper.get_header("Date")
        user = patch_helper.get_header("User")

        try:
            scm.apply_patch(
                patch_helper.get_diff(),
                patch_helper.get_commit_description(),
                user,
                date,
            )
        except PatchConflict as exc:
            # TODO how to handle merge conflicts?
            # TODO 999 here should be replaced, or perhaps revision ID becomes optional.
            # breakdown = self.process_merge_conflict(exc, repo, scm, 999)
            # job.error_breakdown = breakdown

            message = (
                # TODO some kind of ID for which patch failed to apply?
                f"Problem while applying patch in revision.\n\n"
                f"{str(exc)}"
            )
            logger.exception(message)
            job.transition_status(LandingJobAction.FAIL, message=message)
            # TODO no notifications required? at least not initially?
            # self.notify_user_of_landing_failure(job)
            return True
        except Exception as e:
            message = (
                # TODO some kind of ID for which patch failed to apply?
                f"Aborting, could not apply patch buffer."
                f"\n{e}"
            )
            logger.exception(message)
            job.transition_status(
                LandingJobAction.FAIL,
                message=message,
            )
            # TODO no notifications required? at least not initially?
            # self.notify_user_of_landing_failure(job)
            return True

        return True

    def process_action(
        self, job: AutomationJob, repo: Repo, scm: AbstractSCM, action: Action
    ) -> bool:
        """Process an automation action."""
        if action.action == "add-commit":
            return self.add_commit_action(job, repo, scm, action)

        raise NotImplementedError(
            f"Action type {action.action} is not yet implemented."
        )

    def run_automation_job(self, job: AutomationJob) -> bool:
        """Run an automation job."""
        repo = job.target_repo
        scm = repo.scm

        # TODO should we check treestatus?

        with scm.for_push(job.requester_email):
            repo_pull_info = f"tree: {repo.tree}, pull path: {repo.pull_path}"
            try:
                # TODO should we always update to the latest pull_path for a repo?
                # or perhaps we need to specify some commit SHA?
                scm.update_repo(repo.pull_path)
            except SCMInternalServerError as e:
                message = (
                    f"`Temporary error ({e.__class__}) "
                    f"encountered while pulling from {repo_pull_info}"
                )
                logger.exception(message)
                job.transition_status(LandingJobAction.DEFER, message=message)

                # Try again, this is a temporary failure.
                return False
            except Exception as e:
                message = f"Unexpected error while fetching repo from {repo.pull_path}."
                logger.exception(message)
                job.transition_status(
                    LandingJobAction.FAIL,
                    message=message + f"\n{e}",
                )
                # TODO no notifications required? at least not initially?
                # self.notify_user_of_landing_failure(job)
                return True

            actions = job.actions.all()
            for action_row in actions:
                # Turn the row action into a Pydantic action.
                action = map_to_pydantic_action(action_row.action_type, action_row.data)

                # Execute the action locally.
                self.process_action(job, repo, scm, action)

            repo_push_info = f"tree: {repo.tree}, push path: {repo.push_path}"
            try:
                scm.push(
                    repo.push_path,
                    push_target=repo.push_target,
                    force_push=repo.force_push,
                )
            except (
                TreeClosed,
                TreeApprovalRequired,
                SCMLostPushRace,
                SCMPushTimeoutException,
                SCMInternalServerError,
            ) as e:
                message = (
                    f"`Temporary error ({e.__class__}) "
                    f"encountered while pushing to {repo_push_info}"
                )
                logger.exception(message)
                job.transition_status(LandingJobAction.DEFER, message=message)
                return False  # Try again, this is a temporary failure.
            except Exception as e:
                message = f"Unexpected error while pushing to {repo.push_path}.\n{e}"
                logger.exception(message)
                job.transition_status(
                    LandingJobAction.FAIL,
                    message=message,
                )
                # TODO no notifications required? at least not initially?
                # self.notify_user_of_landing_failure(job)
                return True  # Do not try again, this is a permanent failure.

            # Get the changeset hash of the first node.
            commit_id = scm.head_ref()

        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        if repo.phab_identifier:
            self.phab_trigger_repo_update(repo.phab_identifier)

        return True

    @staticmethod
    def notify_user_of_landing_failure(job: AutomationJob):
        """Wrapper around notify_user_of_landing_failure for convenience.

        Args:
            job (LandingJob): A LandingJob instance to use when fetching the
                notification parameters.
        """
        notify_user_of_landing_failure(
            job.requester_email, job.landing_job_identifier, job.error, job.id
        )

    @staticmethod
    def phab_trigger_repo_update(phab_identifier: str):
        """Wrapper around `phab_trigger_repo_update` for convenience.

        Args:
            phab_identifier: `str` to be passed to Phabricator to identify
            repo.
        """
        try:
            # Send a Phab repo update task to Celery.
            phab_trigger_repo_update.apply_async(args=(phab_identifier,))
        except kombu.exceptions.OperationalError as e:
            # Log the exception but continue gracefully.
            # The repo will eventually update.
            logger.exception("Failed sending repo update task to Celery.")
            logger.exception(e)
