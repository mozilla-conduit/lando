import json
import logging
import os
import subprocess
import tempfile

from typing_extensions import override

from lando.api.legacy.workers.base import Worker
from lando.main.models import JobAction, PermanentFailureException, WorkerType
from lando.main.models.uplift import UpliftJob, UpliftRevision

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
        scm = repo.scm
        multi_request = job.multi_request
        user = multi_request.user

        # Update to the latest commit in the target train.
        base_revision = self.update_repo(repo, job, scm, target_cset=None)

        # Apply patches to the tip of the target train.
        for uplift_revision in job.revisions.all():
            self.apply_patch(repo, job, scm, uplift_revision)

        # On success: create patches.
        response = self.moz_phab_uplift(
            job, user.profile.phabricator_api_key, base_revision
        )

        commits = response["commits"]
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

        job.created_revision_ids = created_revision_ids
        job.transition_status(JobAction.SUCCESS)

        return True

    def moz_phab_uplift(self, job: UpliftJob, api_key: str, base_revision: str) -> dict:
        """Run `moz-phab uplift` on the repo."""
        target_repo = job.target_repo

        env = os.environ.copy()
        env["MOZPHAB_PHABRICATOR_API_KEY"] = api_key

        with tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w+", suffix="json"
        ) as f_output:
            try:
                subprocess.run(
                    [
                        "moz-phab",
                        "uplift",
                        "--output-file",
                        f_output.name,
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
                message = f"`moz-phab uplift` did not complete successfully: {str(exc)}"
                logger.exception(message)
                job.transition_status(JobAction.FAIL, message=message)
                raise PermanentFailureException(message) from exc

            f_output.seek(0)

            try:
                return json.load(f_output)
            except json.JSONDecodeError as exc:
                message = "`moz-phab uplift` produced invalid JSON output."
                logger.exception(message)
                job.transition_status(JobAction.FAIL, message=message)
                raise PermanentFailureException(message) from exc
