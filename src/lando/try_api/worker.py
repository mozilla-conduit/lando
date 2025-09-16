import base64

from typing_extensions import override

from lando.api.legacy.workers.base import Worker
from lando.main.models import (
    WorkerType,
)
from lando.main.models.commit_map import CommitMap
from lando.main.models.jobs import TemporaryFailureException
from lando.main.scm.consts import SCM_TYPE_HG
from lando.pushlog.pushlog import PushLogForRepo
from lando.try_api.models.job import TryJob


class TryWorker(Worker):
    job_type = TryJob
    worker_type = WorkerType.TRY

    @override
    def run_job(self, job: TryJob) -> bool:
        repo = job.target_repo
        scm = repo.scm

        push_target = f"try-job-{job.id}"

        # XXX: We'll need a more flexible way to set this.
        mapping_repo = "firefox"

        target_commit_hash = job.target_commit_hash
        if job.base_commit_vcs != repo.scm_type:
            try:
                if repo.scm_type == SCM_TYPE_HG:
                    target_commit_hash = CommitMap.git2hg(
                        mapping_repo, target_commit_hash
                    )
                else:
                    target_commit_hash = CommitMap.hg2git(
                        mapping_repo, target_commit_hash
                    )
            except CommitMap.DoesNotExist as exc:
                raise TemporaryFailureException(
                    f"Failed determining equivalent base commit for {target_commit_hash} in {repo.scm_type} for {mapping_repo}: {exc}"
                ) from exc

        with (
            scm.for_push(job.requester_email),
            PushLogForRepo(repo, job.requester_email) as pushlog,
        ):
            scm.update_repo(repo.pull_path, target_commit_hash)

            for patch_b64 in job.patches:
                patch_bytes = base64.b64decode(patch_b64)
                scm.apply_patch_git(patch_bytes)

            new_commits = scm.describe_local_changes(base_cset=target_commit_hash)
            for commit in new_commits:
                pushlog.add_commit(commit)

            scm.push(
                repo.push_path,
                push_target=push_target,
                force_push=repo.force_push,
            )

        return True
