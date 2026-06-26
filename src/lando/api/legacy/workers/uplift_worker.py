import json
import logging
import os
import subprocess
import tempfile
import time
from typing import Iterable

from django.conf import settings
from django.db import transaction
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
from lando.main.models.landing_job import LandingJob, add_revisions_to_job
from lando.main.models.repo import Repo
from lando.main.models.uplift import UpliftJob, UpliftRevision
from lando.main.scm import GitSCM
from lando.main.scm.commit import CommitData
from lando.main.scm.helpers import PatchHelper
from lando.try_api.api import get_commit_hash, get_commit_map
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
        submission = job.submission
        user = submission.requested_by
        job_url = job.url()

        requested_revision_ids = submission.requested_revision_ids

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

        def apply_uplift_revision(revision: Revision):
            """Apply revision to the current branch.

            Cherry-pick a commit to the tip of the target train,
            or apply patches as fallback.
            """
            commit_id = revision.get_latest_landing_commit_id()

            if commit_id and scm.commit_exists(commit_id):
                logger.debug(f"Cherry-picking {revision} with commit_id: {commit_id}")
                try:
                    scm.cherry_pick_commit(commit_id)
                    return
                except NotImplementedError:
                    logger.debug(
                        "Cherry-pick not supported for this SCM type. "
                        "Falling back to applying patch."
                    )
            else:
                logger.debug(
                    f"No landing commit found for {revision}. "
                    f"Falling back to applying patch."
                )

            scm.apply_patch(
                revision.diff,
                revision.commit_message,
                revision.author,
                revision.timestamp,
            )

        repo = job.target_repo
        submission = job.submission
        user = submission.requested_by
        scm = repo.scm

        # Update to the latest commit in the target train.
        base_revision = self.update_repo(repo, job, scm, target_cset=None)
        new_commits = []
        for uplift_revision in job.revisions.all():
            self.handle_new_commit_failures(
                apply_uplift_revision, repo, job, scm, uplift_revision
            )
            new_commit = scm.describe_commit()
            new_commits.append(new_commit)
            logger.debug(f"Created new commit {new_commit}")

        # On success: create patches.
        result = self.create_uplift_revisions(
            job, user.profile.phabricator_api_key, base_revision
        )

        # Retrieve created revision IDs and tip revision ID.
        commits = result["commits"]
        created_revision_ids = [int(commit["rev_id"]) for commit in commits]
        tip_revision_id = created_revision_ids[-1]

        UpliftRevision.link_revision_to_assessment(
            tip_revision_id, submission.assessment
        )

        # Trigger a Celery task to update the form on Phabricator.
        self.call_task(
            set_uplift_request_form_on_revision,
            tip_revision_id,
            submission.assessment.to_conduit_json_str(),
            user.id,
        )

        job.created_revision_ids = created_revision_ids
        # `LANDED` is the same as "success".
        job.status = JobStatus.LANDED
        job.save()

        try:
            try_job = self.create_uplift_try_push(
                base_revision, repo.scm_type, job, scm, new_commits
            )
        except Exception:
            logger.exception(
                "Failed to create try push for uplift job.",
                extra={"job_id": job.id},
            )
        else:
            logger.info(
                "Created try landing job for uplift job.",
                extra={"job_id": job.id, "try_job_id": try_job.id},
            )
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
                    "`moz-phab uplift` may have produced revisions on Phabricator but "
                    "failed while returning results. Please check Phabricator for any "
                    "new revisions."
                )
                logger.exception(
                    message,
                    extra={
                        "moz_phab_json_error": exc.msg,
                        "moz_phab_json_position": exc.pos,
                        "moz_phab_json_raw": exc.doc,
                    },
                )
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
            message = "`moz-phab uplift` did not complete successfully."
            logger.exception(
                message,
                extra={
                    "returncode": exc.returncode,
                    "command": exc.cmd,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                },
            )
            job.transition_status(JobAction.FAIL, message=message)
            raise PermanentFailureException(message) from exc

    def create_uplift_try_push(
        self,
        target_commit_hash: str,
        repo_scm_type: str,
        job: UpliftJob,
        scm: GitSCM,
        new_commits: Iterable[CommitData],
    ) -> LandingJob:
        """Create a Try `LandingJob` for the commits landed by an uplift job."""
        try_repo = Repo.objects.get(name="try")

        if try_repo.scm_type != repo_scm_type:
            try:
                mapping_repo = get_commit_map(
                    try_repo.scm_type, try_repo.name, repo_scm_type
                )
            except ValueError:
                logger.exception(
                    "CommitMap not found",
                    extra={"job_id": job.id},
                )
                raise
            try:
                target_commit_hash = get_commit_hash(
                    mapping_repo, target_commit_hash, try_repo.scm_type
                )
            except ValueError:
                logger.exception(
                    "Error converting SCM commit IDs",
                    extra={"job_id": job.id},
                )
                raise

        with transaction.atomic():
            revisions = []
            patch_helpers = scm.get_patch_helpers_for_commits(new_commits)
            for patch_helper in patch_helpers:
                revisions.append(self.create_revisions_from_patch_helpers(patch_helper))
            try_revision = self.create_try_revision(job.requester_email)
            revisions.append(try_revision)

            try_job = LandingJob.objects.create(
                target_repo=try_repo,
                requester_email=job.requester_email,
                target_commit_hash=target_commit_hash,
                status=JobStatus.SUBMITTED,
            )
            add_revisions_to_job(revisions, try_job)
            try_job.save()
        return try_job

    def create_try_diff_from_json(self) -> str:
        try_config_path = (
            settings.BASE_DIR / "api" / "legacy" / "workers" / "try_task_config.json"
        )
        config_contents = try_config_path.read_text()
        config_lines = config_contents.splitlines()
        diff_header_lines = [
            "diff --git a/try_task_config.json b/try_task_config.json",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/try_task_config.json",
            f"@@ -0,0 +1,{len(config_lines)} @@",
        ]
        added_lines = [f"+{line}" for line in config_lines]
        raw_diff = "\n".join(diff_header_lines + added_lines) + "\n"
        return raw_diff

    def create_try_revision(self, requester_email: str) -> Revision:
        """Build the `Revision` carrying the `try_task_config.json` change."""
        try_patch_data = {
            "author_name": "Lando",
            "author_email": requester_email,
            "commit_message": "try_task_config",
            "timestamp": str(int(time.time())),
        }
        raw_diff = self.create_try_diff_from_json()
        return Revision.new_from_patch(raw_diff=raw_diff, patch_data=try_patch_data)

    def create_revisions_from_patch_helpers(
        self, patch_helper: PatchHelper
    ) -> Revision:
        """Build a `Revision` from a single landed commit's `PatchHelper`."""
        author_name, author_email = patch_helper.parse_author_information()
        timestamp = patch_helper.get_timestamp()
        commit_message = patch_helper.get_commit_description()
        diff = patch_helper.get_diff()
        patch_data = {
            "author_name": author_name,
            "author_email": author_email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        }
        return Revision.new_from_patch(raw_diff=diff, patch_data=patch_data)
