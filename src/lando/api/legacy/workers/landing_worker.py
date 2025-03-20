from __future__ import annotations

import configparser
import logging
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import (
    Optional,
)

import kombu
from django.db import transaction

from lando.api.legacy.commit_message import bug_list_to_commit_string, parse_bugs
from lando.api.legacy.notifications import (
    notify_user_of_bug_update_failure,
    notify_user_of_landing_failure,
)
from lando.api.legacy.uplift import (
    update_bugs_for_uplift,
)
from lando.api.legacy.workers.base import Worker
from lando.main.models.landing_job import LandingJob, LandingJobAction, LandingJobStatus
from lando.main.models.repo import Repo
from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.exceptions import (
    AutoformattingException,
    NoDiffStartLine,
    PatchConflict,
    SCMException,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.utils.config import read_lando_config
from lando.utils.tasks import phab_trigger_repo_update

logger = logging.getLogger(__name__)

AUTOFORMAT_COMMIT_MESSAGE = """
{bugs}: apply code formatting via Lando

# ignore-this-changeset
""".strip()


@contextmanager
def job_processing(job: LandingJob):
    """Mutex-like context manager that manages job processing miscellany.

    This context manager facilitates graceful worker shutdown, tracks the duration of
    the current job, and commits changes to the DB at the very end.

    Args:
        job: the job currently being processed
    """
    start_time = datetime.now()
    try:
        yield
    finally:
        job.duration_seconds = (datetime.now() - start_time).seconds
        job.save()


class LandingWorker(Worker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_job_finished = None
        self.refresh_active_repos()

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
            job = LandingJob.next_job(repositories=self.active_repos).first()

        if job is None:
            self.throttle(self.worker_instance.sleep_seconds)
            return

        with job_processing(job):
            job.status = LandingJobStatus.IN_PROGRESS
            job.attempts += 1
            job.save()

            # Make sure the status and attempt count are updated in the database
            logger.info("Starting landing job", extra={"id": job.id})
            self.last_job_finished = self.run_job(job)
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

    def autoformat(
        self,
        job: LandingJob,
        scm: AbstractSCM,
        bug_ids: list[str],
        changeset_titles: list[str],
    ) -> Optional[str]:
        """
        Determine and apply the repo's autoformatting rules.

        If no `.lando.ini` configuration can be found in the repo, autoformatting is skipped with a warning, but returns a success status.

        Returns: Optional[str]
            None: no error
            str: error message
        """
        # Load repo-specific configuration.
        try:
            lando_ini_contents = scm.read_checkout_file(".lando.ini")
        except ValueError:
            logger.warning(
                "No .lando.ini configuration found in repo, skipping autoformatting"
            )
            # Not a failure per se.
            return

        landoini_config = read_lando_config(lando_ini_contents)

        try:
            replacements = self.apply_autoformatting(
                scm,
                landoini_config,
                bug_ids,
                changeset_titles,
            )
        except AutoformattingException as exc:
            message = (
                "Lando failed to format your patch for conformity with our "
                "formatting policy. Please see the details below.\n\n"
                f"{exc.details()}"
            )

            logger.exception(message)

            return message

        # If autoformatting added any changesets, note those in the job.
        if replacements:
            job.formatted_replacements = replacements

        return

    def run_job(self, job: LandingJob) -> bool:
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
        repo: Repo = job.target_repo
        scm = repo.scm

        if not self.treestatus_client.is_open(repo.tree):
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.tree} is closed - retrying later.",
            )
            return False

        with scm.for_push(job.requester_email):
            # Update local repo.
            repo_pull_info = f"tree: {repo.tree}, pull path: {repo.pull_path}"
            try:
                scm.update_repo(repo.pull_path, target_cset=job.target_commit_hash)
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
                message = f"Unexpected error while fetching repo from {repo.name}."
                logger.exception(message)
                job.transition_status(
                    LandingJobAction.FAIL,
                    message=message + f"\n{e}",
                )
                self.notify_user_of_landing_failure(job)
                return True

            # Run through the patches one by one and try to apply them.
            for revision in job.revisions.all():

                try:
                    scm.apply_patch(
                        revision.diff,
                        revision.commit_message,
                        revision.author,
                        revision.timestamp,
                    )
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

                except PatchConflict as exc:
                    breakdown = scm.process_merge_conflict(
                        repo.pull_path, revision.revision_id, str(exc)
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
            changeset_titles = scm.changeset_descriptions()

            # Parse bug numbers from commits in the stack.
            bug_ids = [
                str(bug) for title in changeset_titles for bug in parse_bugs(title)
            ]

            # Run automated code formatters if enabled.
            if repo.autoformat_enabled and (
                message := self.autoformat(job, scm, bug_ids, changeset_titles)
            ):
                job.transition_status(LandingJobAction.FAIL, message=message)
                self.notify_user_of_landing_failure(job)
                return False

            # Get the changeset hash of the first node.
            commit_id = scm.head_ref()

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
                message = f"Unexpected error while pushing to {repo.name}.\n{e}"
                logger.exception(message)
                job.transition_status(
                    LandingJobAction.FAIL,
                    message=message,
                )
                self.notify_user_of_landing_failure(job)
                return True  # Do not try again, this is a permanent failure.

        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)

        mots_path = Path(repo.path) / "mots.yaml"
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
                    repo.short_name,
                    scm.read_checkout_file("config/milestone.txt"),
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

    def apply_autoformatting(
        self,
        scm: AbstractSCM,
        landoini_config: Optional[configparser.ConfigParser],
        bug_ids: list[str],
        changeset_titles: list[str],
    ) -> Optional[list[str]]:
        try:
            self.format_stack(landoini_config, scm.path)
        except AutoformattingException as exc:
            logger.warning("Failed to format the stack.")
            logger.exception(exc)
            raise exc

        try:
            replacements = self.commit_autoformatting_changes(
                scm, len(changeset_titles), bug_ids
            )
        except SCMException as exc:
            msg = "Failed to create an autoformat commit."
            logger.warning(msg)
            logger.exception(exc)
            raise AutoformattingException(msg, exc.out, exc.err) from exc

        return replacements

    def format_stack(
        self, landoini_config: configparser.ConfigParser, repo_path: str
    ) -> None:
        """Format the patch stack for landing.

        Return a list of `str` commit hashes where autoformatting was applied,
        or `None` if autoformatting was skipped. Raise `AutoformattingException`
        if autoformatting failed for the current job.
        """
        # If `mach` is not at the root of the repo, we can't autoformat.
        if not self.mach_path(repo_path):
            logger.info("No `./mach` in the repo - skipping autoformat.")
            return None

        try:
            self.run_code_formatters(repo_path)
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to run automated code formatters.")
            logger.exception(exc)

            raise AutoformattingException(
                "Failed to run automated code formatters.",
                details=exc.stdout,
            )

    def run_code_formatters(self, path: str) -> str:
        """Run automated code formatters, returning the output of the process.

        Changes made by code formatters are applied to the working directory and
        are not committed into version control.
        """
        return self.run_mach_command(
            path, ["format", "--fix", "--outgoing", "--verbose"]
        )

    def run_mach_bootstrap(self, path: str) -> str:
        """Run `mach bootstrap` to configure the system for code formatting."""
        return self.run_mach_command(
            path,
            [
                "bootstrap",
                "--no-system-changes",
                "--application-choice",
                "browser",
            ],
        )

    def run_mach_command(self, path: str, args: list[str]) -> str:
        """Run a command using the local `mach`, raising if it is missing."""
        if not self.mach_path(path):
            raise Exception("No `mach` found in local repo!")

        # Convert to `str` here so we can log the mach path.
        command_args = [str(self.mach_path(path))] + args

        try:
            logger.info("running mach command", extra={"command": command_args})

            output = subprocess.run(
                command_args,
                capture_output=True,
                check=True,
                cwd=path,
                encoding="utf-8",
                universal_newlines=True,
            )

            logger.info(
                "output from mach command",
                extra={
                    "output": output.stdout,
                },
            )

            return output.stdout

        except subprocess.CalledProcessError as exc:
            logger.exception(
                "Failed to run mach command",
                extra={
                    "command": command_args,
                    "err": exc.stderr,
                    "output": exc.stdout,
                },
            )

            raise exc

    def mach_path(self, path: str) -> Optional[Path]:
        """Return the `Path` to `mach`, if it exists."""
        mach_path = Path(path) / "mach"
        if mach_path.exists():
            return mach_path

    def commit_autoformatting_changes(
        self, scm: AbstractSCM, stack_size: int, bug_ids: list[str]
    ) -> Optional[list[str]]:
        """Call the SCM implementation to commit pending autoformatting changes.

        If the `stack_size` is 1, the tip commit will get amended. Otherwise, a new
        commit will be created on top of the stack (referencing all bugs involved in the
        stack).
        """
        # When the stack is just a single commit, amend changes into it.
        if stack_size == 1:
            return scm.format_stack_amend()

        # If the stack is more than a single commit, create an autoformat commit.
        bug_string = bug_list_to_commit_string(bug_ids)
        return scm.format_stack_tip(AUTOFORMAT_COMMIT_MESSAGE.format(bugs=bug_string))
