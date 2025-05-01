import logging

import kombu
from django.db import transaction

from lando.api.legacy.workers.base import Worker
from lando.headless_api.api import (
    AutomationActionException,
    resolve_action,
)
from lando.headless_api.models.automation_job import (
    AutomationJob,
)
from lando.main.models.landing_job import JobAction, JobStatus
from lando.main.scm.exceptions import (
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.pushlog.pushlog import PushLogForRepo
from lando.utils.tasks import phab_trigger_repo_update

logger = logging.getLogger(__name__)


class AutomationWorker(Worker):
    """Worker to execute automation jobs.

    This worker runs `AutomationJob`s on enabled repositories.
    These jobs include a set of actions which are to be run on the repository,
    and then pushed to the destination repo.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_job_finished = None
        self.refresh_active_repos()

    def refresh_active_repos(self):
        """Override base functionality by not checking treestatus."""
        self.active_repos = self.enabled_repos

    def loop(self):
        logger.debug(
            f"{len(self.worker_instance.enabled_repos)} "
            f"enabled repos: {self.worker_instance.enabled_repos}"
        )

        # Refresh repos if there is a mismatch in active vs. enabled repos.
        if len(self.active_repos) != len(self.enabled_repos):
            self.refresh_active_repos()

        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self.worker_instance.sleep_seconds)
            self.refresh_active_repos()

        with transaction.atomic():
            job = AutomationJob.next_job(repositories=self.active_repos).first()

        if job is None:
            self.throttle(self.worker_instance.sleep_seconds)
            return

        with job.processing():
            job.status = JobStatus.IN_PROGRESS
            job.attempts += 1
            job.save()

            # Make sure the status and attempt count are updated in the database
            logger.info("Starting automation job", extra={"id": job.id})
            self.last_job_finished = self.run_automation_job(job)
            logger.info("Finished processing automation job", extra={"id": job.id})

    def run_automation_job(self, job: AutomationJob) -> bool:
        """Run an automation job."""
        repo = job.target_repo
        scm = repo.scm

        with (
            scm.for_push(job.requester_email),
            PushLogForRepo(repo, job.requester_email) as pushlog,
        ):
            repo_pull_info = f"tree: {repo.tree}, pull path: {repo.pull_path}"
            try:
                scm.update_repo(repo.pull_path)
            except SCMInternalServerError as e:
                message = (
                    f"Temporary error ({e.__class__}) "
                    f"encountered while pulling from {repo_pull_info}"
                )
                logger.exception(message)
                job.transition_status(JobAction.DEFER, message=message)

                # Try again, this is a temporary failure.
                return False
            except Exception as e:
                message = f"Unexpected error while fetching repo from {repo.pull_path}."
                logger.exception(message)
                job.transition_status(
                    JobAction.FAIL,
                    message=message + f"\n{e}",
                )
                return True

            # Record any created tags.
            created_tags = []

            # Run each action for the job.
            actions = job.actions.all()
            for action_row in actions:
                # Turn the row action into a Pydantic action.
                action = resolve_action(action_row.data)

                # Execute the action locally.
                try:
                    action.process(job, repo, scm, action_row.order)

                except AutomationActionException as exc:
                    logger.exception(exc.message)
                    job.transition_status(exc.job_status, message=exc.message)
                    return not exc.is_fatal

                if action.action == "tag":
                    # Record tag if created.
                    tag_name = action.name
                    created_tags.append(tag_name)

            # We need to add the commits to the pushlog _before_ pushing, so we can
            # compare the current stack to the last upstream.
            # We'll only confirm them if the push succeeds.
            for commit in scm.describe_local_changes():
                pushlog.add_commit(commit)

            # We need to add the tags after the commits, in case a `Tag` is created
            # which refers to a commit which does not exist.
            for tag_name in created_tags:
                tag_commitdata = scm.describe_commit(tag_name)
                pushlog.add_tag(tag_name, tag_commitdata)

            repo_push_info = f"tree: {repo.tree}, push path: {repo.push_path}"
            try:
                scm.push(
                    repo.push_path,
                    push_target=repo.push_target,
                    force_push=repo.force_push,
                    tags=created_tags,
                )
            except (
                TreeClosed,
                TreeApprovalRequired,
                SCMLostPushRace,
                SCMPushTimeoutException,
                SCMInternalServerError,
            ) as e:
                message = (
                    f"Temporary error ({e.__class__}) "
                    f"encountered while pushing to {repo_push_info}"
                )
                logger.exception(message)
                job.transition_status(JobAction.DEFER, message=message)
                return False  # Try again, this is a temporary failure.
            except Exception as e:
                message = f"Unexpected error while pushing to {repo.push_path}.\n{e}"
                logger.exception(message)
                job.transition_status(
                    JobAction.FAIL,
                    message=message,
                )
                return True  # Do not try again, this is a permanent failure.
            else:
                pushlog.confirm()

            # Get the changeset hash of the first node.
            commit_id = scm.head_ref()

        job.transition_status(JobAction.LAND, commit_id=commit_id)

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        if repo.phab_identifier:
            self.phab_trigger_repo_update(repo.phab_identifier)

        return True

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
