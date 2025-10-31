import json
import logging
import os
import subprocess
import tempfile

from typing_extensions import override

from lando.api.legacy.workers.base import Worker
from lando.main.models import (
    JobAction,
    JobStatus,
    PermanentFailureException,
    Revision,
    TemporaryFailureException,
    WorkerType,
)
from lando.main.models.uplift import UpliftJob, UpliftRevision
from lando.utils.tasks import (
    send_uplift_failure_email,
    send_uplift_success_email,
    set_uplift_request_form_on_revision,
)

logger = logging.getLogger(__name__)


class UpliftWorker(Worker):
    """Worker to execute uplift jobs.

    This worker runs `UpliftJob`s on enabled repositories.
    These jobs apply patches to respositories and create new Phabricator
    revisions on success.
    """

    job_type = UpliftJob

    worker_type = WorkerType.UPLIFT

    @override
    def refresh_active_repos(self):
        """Override base functionality by not checking treestatus."""
        self.active_repos = self.enabled_repos

    @override
    def run_job(self, job: UpliftJob) -> bool:
        """Run an uplift job."""
        repo = job.target_repo
        user = job.multi_request.user
        job_url = job.url()

        requested_revision_ids = job.multi_request.requested_revisions

        try:
            created_revision_ids = self.apply_and_uplift(job)
        except TemporaryFailureException:
            return False
        except PermanentFailureException:
            self.notify_uplift_failure(
                job, repo.name, job_url, user.email, requested_revision_ids
            )
            return False
        except Exception:  # pragma: no cover - defensive catch
            self.notify_uplift_failure(
                job, repo.name, job_url, user.email, requested_revision_ids
            )
            return False

        self.notify_uplift_success(
            repo.name,
            job_url,
            user.email,
            created_revision_ids,
            requested_revision_ids,
        )
        return True

    def apply_and_uplift(self, job: UpliftJob) -> list[int]:
        """Apply uplift patches to the repo and create new revisions.

        Returns an ordered list of created revision IDs.
        """

        def log_apply_patch(revision: Revision):
            """Apply patches to the tip of the target train."""
            logger.debug(f"Landing {revision} ...")
            scm.apply_patch(
                revision.diff,
                revision.commit_message,
                revision.author,
                revision.timestamp,
            )

        repo = job.target_repo
        multi_request = job.multi_request
        user = multi_request.user
        scm = repo.scm

        # Update to the latest commit in the target train.
        base_revision = self.update_repo(repo, job, scm, target_cset=None)

        for uplift_revision in job.revisions.all():
            self.handle_new_commit_failures(
                log_apply_patch, repo, job, scm, uplift_revision
            )
            new_commit = scm.describe_commit()
            logger.debug(f"Created new commit {new_commit}")

        # On success: create patches.
        result = self.create_uplift_revisions(
            job, user.profile.phabricator_api_key, base_revision
        )

        # Retrieve created revision IDs and tip revision ID.
        commits = result["commits"]
        created_revision_ids = [int(commit["rev_id"]) for commit in commits]
        tip_revision_id = created_revision_ids[-1]

        _, created = UpliftRevision.objects.get_or_create(
            revision_id=tip_revision_id,
            defaults={"assessment": multi_request.assessment},
        )
        if not created:
            UpliftRevision.objects.filter(revision_id=tip_revision_id).update(
                assessment=multi_request.assessment
            )

        # Trigger a Celery task to update the form on Phabricator.
        self.call_task(
            set_uplift_request_form_on_revision,
            tip_revision_id,
            multi_request.assessment.to_conduit_json_str(),
            user.id,
        )

        job.created_revision_ids = created_revision_ids
        # `LANDED` is the same as "success".
        job.status = JobStatus.LANDED
        job.save()

        return created_revision_ids

    def notify_uplift_success(
        self,
        repo_label: str,
        job_url: str,
        recipient_email: str,
        created_revision_ids: list[int],
        requested_revision_ids: list[int],
    ) -> None:
        """Send an uplift success notification email."""
        self.call_task(
            send_uplift_success_email,
            recipient_email,
            repo_label,
            job_url,
            created_revision_ids,
            requested_revision_ids,
        )

    def notify_uplift_failure(
        self,
        job: UpliftJob,
        repo_label: str,
        job_url: str,
        recipient_email: str,
        requested_revision_ids: list[int],
    ) -> None:
        """Send an uplift failure notification email.

        Args:
            job: The uplift job that failed.
            repo_label: Human-readable repository name.
            job_url: URL to view job details.
            recipient_email: Email address to send notification to.
            reason: Error message describing the failure.
            requested_revision_ids: List of Phabricator revision IDs that were being uplifted.
        """
        self.call_task(
            send_uplift_failure_email,
            recipient_email,
            repo_label,
            job_url,
            job.error,
            requested_revision_ids,
        )

    def create_uplift_revisions(
        self, job: UpliftJob, api_key: str, base_revision: str
    ) -> dict:
        """Create Phabricator uplift revisions using `moz-phab uplift`."""
        env = os.environ.copy()
        env["MOZPHAB_PHABRICATOR_API_TOKEN"] = api_key

        with tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w+", suffix="json"
        ) as f_output:
            self.run_moz_phab_uplift(job, base_revision, env, f_output.name)

            f_output.seek(0)

            try:
                return json.load(f_output)
            except json.JSONDecodeError as exc:
                message = (
                    f"`moz-phab uplift` produced invalid JSON output: {exc.msg}"
                    f"\n\n{exc.doc}"
                )
                logger.exception(message)
                job.transition_status(JobAction.FAIL, message=message)
                raise PermanentFailureException(message) from exc

    def run_moz_phab_uplift(
        self,
        job: UpliftJob,
        base_revision: str,
        env: dict[str, str],
        output_path: str,
    ) -> None:
        """Invoke `moz-phab uplift` for the given job and capture the output."""
        target_repo = job.target_repo
        try:
            subprocess.run(
                [
                    "moz-phab",
                    "uplift",
                    # Use `--yes` to avoid confirmation prompts.
                    "--yes",
                    # Use `--no-rebase` as Lando has already applied
                    # patches to the tip of the target train.
                    "--no-rebase",
                    "--output-file",
                    output_path,
                    "--train",
                    target_repo.short_name,
                    base_revision,
                    "HEAD",
                ],
                capture_output=True,
                check=True,
                cwd=target_repo.system_path,
                encoding="utf-8",
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            message = "`moz-phab uplift` did not complete successfully."
            details = [
                f"Return code: {exc.returncode}",
                f"Command: {' '.join(exc.cmd)}",
            ]
            if stdout:
                details.append(f"stdout:\n{stdout}")
            if stderr:
                details.append(f"stderr:\n{stderr}")
            message = f"{message}\n" + "\n".join(details)
            logger.exception(message)
            if stdout:
                logger.error("`moz-phab uplift` stdout:\n%s", stdout)
            if stderr:
                logger.error("`moz-phab uplift` stderr:\n%s", stderr)
            job.transition_status(JobAction.FAIL, message=message)
            raise PermanentFailureException(message) from exc
