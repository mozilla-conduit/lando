from __future__ import annotations

import configparser
import logging
import subprocess
from pathlib import Path

import sentry_sdk
from typing_extensions import override

from lando.api.legacy.commit_message import bug_list_to_commit_string, parse_bugs
from lando.api.legacy.notifications import (
    notify_user_of_bug_update_failure,
    notify_user_of_landing_failure,
)
from lando.api.legacy.uplift import (
    update_bugs_for_uplift,
)
from lando.api.legacy.workers.base import Worker
from lando.main.models import (
    JobAction,
    LandingJob,
    PermanentFailureException,
    Repo,
    TemporaryFailureException,
    WorkerType,
)
from lando.main.scm import (
    AbstractSCM,
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
from lando.pushlog.pushlog import PushLog, PushLogForRepo
from lando.utils.config import read_lando_config
from lando.utils.landing_checks import LandingChecks
from lando.utils.tasks import phab_trigger_repo_update

logger = logging.getLogger(__name__)

AUTOFORMAT_COMMIT_MESSAGE = """
{bugs}: apply code formatting via Lando

# ignore-this-changeset
""".strip()


class LandingWorker(Worker):
    job_type = LandingJob

    worker_type = WorkerType.LANDING

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

    @override
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
                JobAction.DEFER,
                message=f"Tree {repo.tree} is closed - retrying later.",
            )
            return False

        with (
            scm.for_push(job.requester_email),
            PushLogForRepo(repo, job.requester_email) as pushlog,
        ):
            try:
                bug_ids, commit_id = self.apply_and_push(job, repo, scm, pushlog)
            except PermanentFailureException:
                self.notify_user_of_landing_failure(job)
                return True
            except TemporaryFailureException:
                return False

        job.transition_status(JobAction.LAND, commit_id=commit_id)

        mots_path = Path(repo.path) / "mots.yaml"
        if mots_path.exists():
            logger.info(f"{mots_path} found, setting reviewer data.")
            job.set_landed_reviewers(mots_path)
            job.save()
        else:
            logger.info(f"{mots_path} not found, skipping setting reviewer data.")

        # Extra steps for post-uplift landings.
        if repo.approval_required and bug_ids:
            try:
                # If we just landed an uplift, update the relevant bugs as appropriate.
                update_bugs_for_uplift(
                    # Use the `legacy source` shortname here, since the new repos
                    # use the `firefox-` prefix naming convention. For `firefox-beta`
                    # this should return `beta`, etc.
                    repo.default_branch,
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
            self.call_task(phab_trigger_repo_update, repo.phab_identifier)

        return True

    def apply_and_push(
        self,
        job: LandingJob,
        repo: Repo,
        scm: AbstractSCM,
        pushlog: PushLog,
    ) -> tuple[list[str], str]:
        """Apply patches in the job, and pushes them.

        Returns a tuple of bug_ids and tip commit_id.
        """
        self.update_repo(repo, job, scm, job.target_commit_hash)

        # Run through the patches one by one and try to apply them.
        logger.debug(
            f"About to land {job.revisions.count()} revisions: {job.revisions.all()} ..."
        )
        for revision in job.revisions.all():
            try:
                logger.debug(f"Landing {revision} ...")
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
            else:
                new_commit = scm.describe_commit()
                logger.debug(f"Created new commit {new_commit}")

        # Get the changeset titles for the stack.
        changeset_titles = scm.changeset_descriptions()

        # Parse bug numbers from commits in the stack.
        bug_ids = [str(bug) for title in changeset_titles for bug in parse_bugs(title)]

        # Run automated code formatters if enabled.
        if repo.autoformat_enabled and (
            message := self.autoformat(job, scm, bug_ids, changeset_titles)
        ):
            job.transition_status(JobAction.FAIL, message=message)
            self.notify_user_of_landing_failure(job)
            raise TemporaryFailureException(message)

        # Get the changeset hash of the first node.
        commit_id = scm.head_ref()

        new_commits = scm.describe_local_changes()

        if repo.hooks_enabled:
            landing_checks = LandingChecks(repo, job.requester_email)
            try:
                check_errors = landing_checks.run(new_commits)
            except Exception as exc:
                message = "Unexpected error while performing landing checks."
                logger.exception(message)
                job.transition_status(
                    JobAction.FAIL,
                    message=f"{message}\n{exc}",
                )
                raise PermanentFailureException(message) from exc

            if check_errors:
                message = "Some checks failed before attempting to land:\n" + "\n".join(
                    check_errors
                )
                logger.warning(message)
                job.transition_status(
                    JobAction.FAIL,
                    message=message,
                )
                raise PermanentFailureException(message)

        # We need to add the commits to the pushlog _before_ pushing, so we can
        # compare the current stack to the last upstream.
        # We'll only confirm them if the push succeeds.
        for commit in new_commits:
            pushlog.add_commit(commit)
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
                f"encountered while pushing to {repo_push_info}: {e}"
            )
            logger.exception(message)
            job.transition_status(JobAction.DEFER, message=message)
            raise TemporaryFailureException(message)
        except Exception as exc:
            message = f"Unexpected error while pushing to {repo.name}."
            logger.exception(message)
            job.transition_status(
                JobAction.FAIL,
                message=f"{message}\n{exc}",
            )
            raise PermanentFailureException(message) from exc
        else:
            pushlog.confirm()

        return bug_ids, commit_id

    def autoformat(
        self,
        job: LandingJob,
        scm: AbstractSCM,
        bug_ids: list[str],
        changeset_titles: list[str],
    ) -> str | None:
        """
        Determine and apply the repo's autoformatting rules.

        If no `.lando.ini` configuration can be found in the repo, autoformatting is skipped with a warning, but returns a success status.

        Returns: str | None
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

    def apply_autoformatting(
        self,
        scm: AbstractSCM,
        landoini_config: configparser.ConfigParser | None,
        bug_ids: list[str],
        changeset_titles: list[str],
    ) -> list[str] | None:
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
            path, ["format", "--fix", "--outgoing", "--verbose", "--skip-android"]
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

    def mach_path(self, path: str) -> Path | None:
        """Return the `Path` to `mach`, if it exists."""
        mach_path = Path(path) / "mach"
        if mach_path.exists():
            return mach_path

    def commit_autoformatting_changes(
        self, scm: AbstractSCM, stack_size: int, bug_ids: list[str]
    ) -> list[str] | None:
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

    def bootstrap_repos(self):
        """Optional method to bootstrap repositories in the the work directory."""
        logger.info("Bootstrapping applicable repos...")
        repos = self.worker_instance.enabled_repos.filter(autoformat_enabled=True)
        command = [
            "bootstrap",
            "--no-system-changes",
            "--application-choice",
            "browser",
        ]

        for repo in repos:
            try:
                self.run_mach_command(repo.path, command)
            except subprocess.CalledProcessError as exc:
                logger.warning(
                    f"Error `running mach` bootstrap for repo {repo.name}: {exc}"
                )
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                logger.warning(
                    f"Unexpected error `running mach` bootstrap for repo {repo.name}: {exc}"
                )
