from __future__ import annotations

import logging
import os
import re
import subprocess
from io import StringIO
from pathlib import Path
from typing import Any

import kombu
from django.conf import settings
from django.db import transaction
from lando.api.legacy.commit_message import parse_bugs
from lando.api.legacy.notifications import (
    notify_user_of_bug_update_failure,
    notify_user_of_landing_failure,
)
from lando.api.legacy.uplift import (
    update_bugs_for_uplift,
)
from lando.main.interfaces.hg_repo_interface import (
    REJECTS_PATH,
    AutoformattingException,
    HgmoInternalServerError,
    HgRepoInterface,
    LostPushRace,
    NoDiffStartLine,
    PatchConflict,
    PushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.main.models.landing_job import LandingJob, LandingJobAction, LandingJobStatus
from lando.main.models.repo import Repo
from lando.main.util import get_repos_for_env
from lando.main.workers.base_worker import BaseWorker, job_processing
from lando.utils.tasks import phab_trigger_repo_update

logger = logging.getLogger(__name__)


class HgLandingWorker(BaseWorker):

    def __init__(self, stdout=None, with_ssh: bool = True, *args, **kwargs):
        super().__init__(stdout, *args, **kwargs)

        # The list of all repos that are enabled for this worker
        self.applicable_repos = get_repos_for_env(settings.ENVIRONMENT).items()

        # The list of all repos that have open trees; refreshed when needed via
        # `self.refresh_enabled_repos`.
        self.enabled_repos = []

        self.refresh_enabled_repos()

        SSH_PRIVATE_KEY_ENV_KEY = "SSH_PRIVATE_KEY"

        if with_ssh:
            # Fetch ssh private key from the environment. Note that this key should be
            # stored in standard format including all new lines and new line at the end
            # of the file.
            self.ssh_private_key = os.environ.get(SSH_PRIVATE_KEY_ENV_KEY)
            if not self.ssh_private_key:
                logger.warning(f"No {SSH_PRIVATE_KEY_ENV_KEY} present in environment.")

    @property
    def name(self):
        return "hg-landing-worker"

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        self.last_job_finished = None
        self.start()

    def _setup(self):
        """Perform various setup actions."""
        if hasattr(self, "ssh_private_key"):
            self._setup_ssh(self.ssh_private_key)

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

    def refresh_enabled_repos(self):
        """Refresh the list of repositories based on treestatus."""
        # self.enabled_repos = [
        #    repo
        #    for name, repo in self.applicable_repos
        #    if treestatus_subsystem.client.is_open(name)
        # ]
        logger.info(f"{len(self.enabled_repos)} enabled repos: {self.enabled_repos}")

    def loop(self, *args, **kwargs):
        logger.debug(
            f"{len(self.applicable_repos)} applicable repos: {self.applicable_repos}"
        )

        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self._instance.sleep_seconds)
            self.refresh_enabled_repos()

        with transaction.atomic():
            repository_names = [repo.name for repo in self._instance.enabled_repos]
            job = LandingJob.next_job(repository_names=repository_names).first()

            if job is None:
                self.throttle(self._instance.sleep_seconds)
                return

            with job_processing(job):
                job.status = LandingJobStatus.IN_PROGRESS
                job.attempts += 1
                job.save()

                logger.info("Starting landing job", extra={"id": job.id})
                self.last_job_finished = self.run_job(
                    job,
                    job.target_repo,
                    # treestatus_subsystem.client,
                )
                logger.info("Finished processing landing job", extra={"id": job.id})

    @staticmethod
    def notify_user_of_landing_failure(job: LandingJob):
        """Wrapper around notify_user_of_landing_failure for convenience.

        Args:
            job (LandingJob): A LandingJob instance to use when fetching the
                notification parameters.
        """
        notify_user_of_landing_failure(
            job.requester_email, job.landing_job_identifier, job.error, job.id
        )

    def process_merge_conflict(
        self,
        exception: PatchConflict,
        repo: Repo,
        local_repo_interface: HgRepoInterface,
        revision_id: int,
    ) -> dict[str, Any]:
        """Extract and parse merge conflict data from exception into a usable format."""
        failed_paths, reject_paths = self.extract_error_data(str(exception))

        # Find last commits to touch each failed path.
        failed_path_changesets = [
            (
                path,
                local_repo_interface.run(
                    [
                        "log",
                        "--cwd",
                        repo.system_path,
                        "--template",
                        "{node}",
                        "-l",
                        "1",
                        path,
                    ]
                ),
            )
            for path in failed_paths
        ]

        breakdown = {
            "revision_id": revision_id,
            "content": None,
            "reject_paths": {},
            "failed_paths": [
                {
                    "path": path[0],
                    "url": f"{repo.pull_path}/file/{path[1].decode('utf-8')}/{path[0]}",
                    "changeset_id": path[1].decode("utf-8"),
                }
                for path in failed_path_changesets
            ],
        }

        for path in reject_paths:
            reject = {"path": path}
            try:
                with open(REJECTS_PATH / repo.system_path[1:] / path, "r") as f:
                    reject["content"] = f.read()
            except Exception as e:
                logger.exception(e)
            # Use actual path of file to store reject data, by removing
            # `.rej` extension.
            breakdown["reject_paths"][path[:-4]] = reject
        return breakdown

    @staticmethod
    def notify_user_of_bug_update_failure(job: LandingJob, exception: Exception):
        """Wrapper around notify_user_of_bug_update_failure for convenience.

        Args:
            job (LandingJob): A LandingJob instance to use when fetching the
                notification parameters.
        """
        notify_user_of_bug_update_failure(
            job.requester_email,
            job.landing_job_identifier,
            f"Failed to update Bugzilla after landing uplift revisions: {str(exception)}",
            job.id,
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

    @staticmethod
    def extract_error_data(exception: str) -> tuple[list[str], list[str]]:
        """Extract rejected hunks and file paths from exception message."""
        # RE to capture .rej file paths.
        rejs_re = re.compile(
            r"^\d+ out of \d+ hunks FAILED -- saving rejects to file (.+)$",
            re.MULTILINE,
        )

        # TODO: capture reason for patch failure, e.g. deleting non-existing file, or
        # adding a pre-existing file, etc...
        reject_paths = rejs_re.findall(exception)

        # Collect all failed paths by removing `.rej` extension.
        failed_paths = [path[:-4] for path in reject_paths]

        return failed_paths, reject_paths

    def run_job(
        self,
        job: LandingJob,
        repo: Repo,
        # treestatus: TreeStatus,
    ) -> bool:
        """Run a given LandingJob and return appropriate boolean state.

        Running a landing job goes through the following steps:
        - Check treestatus.
        - Update local repo with latest and prepare for import.
        - Apply each patch to the repo.
        - Perform additional processes and checks (e.g., code formatting).
        - Push changes to remote repo.

        Returns:
            True: The job finished processing and is in a permanent state.
            False: The job encountered a temporary failure and should be tried again.
        """
        """
        if not treestatus.is_open(repo.name):
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.name} is closed - retrying later.",
            )
            return False
        """
        with repo.interface.push_context(job.requester_email):
            # Update local repo.
            try:
                repo.interface.update_repo(
                    pull_path=repo.pull_path, target_cset=job.target_commit_hash
                )
            except HgmoInternalServerError as e:
                message = (
                    f"`Temporary error ({e.__class__}) "
                    f"encountered while pulling from name: {repo.name}, pull path: {repo.pull_path}"
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
                self.notify_user_of_landing_failure(job)
                return True

            # Run through the patches one by one and try to apply them.
            for revision in job.revisions.all():
                patch_buf = StringIO(revision.patch_string)

                try:
                    repo.interface.apply_patch(patch_buf)
                except PatchConflict as exc:
                    breakdown = self.process_merge_conflict(
                        exc, repo, repo.interface, revision.revision_id
                    )
                    job.error_breakdown = breakdown

                    message = (
                        f"Problem while applying patch in revision {revision.revision_id}:\n\n"
                        f"{str(exc)}"
                    )
                    logger.exception(message)
                    job.transition_status(LandingJobAction.FAIL, message=message)
                    self.notify_user_of_landing_failure(job)
                    return True
                except NoDiffStartLine:
                    message = (
                        "Lando encountered a malformed patch, please try again. "
                        "If this error persists please file a bug: "
                        "Patch without a diff start line."
                    )
                    logger.error(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message,
                    )
                    self.notify_user_of_landing_failure(job)
                    return True
                except Exception as e:
                    message = (
                        f"Aborting, could not apply patch buffer for {revision.revision_id}."
                        f"\n{e}"
                    )
                    logger.exception(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message,
                    )
                    self.notify_user_of_landing_failure(job)
                    return True

            # Get the changeset titles for the stack.
            changeset_titles = (
                repo.interface.run(["log", "-r", "stack()", "-T", "{desc|firstline}\n"])
                .decode("utf-8")
                .splitlines()
            )

            # Parse bug numbers from commits in the stack.
            bug_ids = [
                str(bug) for title in changeset_titles for bug in parse_bugs(title)
            ]

            # Run automated code formatters if enabled.
            if repo.autoformat_enabled:
                try:
                    replacements = repo.interface.format_stack(
                        len(changeset_titles), bug_ids
                    )

                    # If autoformatting added any changesets, note those in the job.
                    if replacements:
                        job.formatted_replacements = replacements

                except AutoformattingException as exc:
                    message = (
                        "Lando failed to format your patch for conformity with our "
                        "formatting policy. Please see the details below.\n\n"
                        f"{exc.details()}"
                    )

                    logger.exception(message)

                    job.transition_status(LandingJobAction.FAIL, message=message)
                    self.notify_user_of_landing_failure(job)
                    return False

            # Get the changeset hash of the first node.
            commit_id = repo.interface.run(["log", "-r", ".", "-T", "{node}"]).decode(
                "utf-8"
            )

            repo_push_info = f"name: {repo.name}, push path: {repo.push_path}"
            try:
                repo.interface.push(
                    repo.push_path,
                    bookmark=repo.push_bookmark or None,
                    force_push=repo.force_push,
                )
            except (
                TreeClosed,
                TreeApprovalRequired,
                LostPushRace,
                PushTimeoutException,
                HgmoInternalServerError,
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
                self.notify_user_of_landing_failure(job)
                return True  # Do not try again, this is a permanent failure.

        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)

        mots_path = Path(repo.system_path) / "mots.yaml"
        if mots_path.exists():
            logger.info(f"{mots_path} found, setting reviewer data.")
            job.set_landed_reviewers(mots_path)
            job.save()
        else:
            logger.info(f"{mots_path} not found, skipping setting reviewer data.")

        # Extra steps for post-uplift landings.
        if repo.approval_required:
            try:
                # If we just landed an uplift, update the relevant bugs as appropriate.
                update_bugs_for_uplift(
                    repo.name,
                    repo.interface.read_checkout_file("config/milestone.txt"),
                    repo.milestone_tracking_flag_template,
                    bug_ids,
                )
            except Exception as e:
                # The changesets will have gone through even if updating the bugs fails. Notify
                # the landing user so they are aware and can update the bugs themselves.
                self.notify_user_of_bug_update_failure(job, e)

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        if repo.phab_identifier:
            self.phab_trigger_repo_update(repo.phab_identifier)

        return True
