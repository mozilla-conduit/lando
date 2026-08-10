import logging

from typing_extensions import override

from lando.api.legacy.workers.base import Worker
from lando.headless_api.api import (
    AutomationActionException,
    resolve_action,
)
from lando.headless_api.models.automation_job import (
    ActionTypeChoices,
    AutomationJob,
)
from lando.main.models import (
    JobAction,
    PermanentFailureException,
    TemporaryFailureException,
    WorkerType,
)
from lando.main.scm import (
    CommitData,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.main.scm.abstract_scm import AbstractSCM
from lando.pushlog.pushlog import PushLogForRepo
from lando.utils.github import GitHubAPIClient, PullRequest
from lando.utils.landing_checks import LandingChecks
from lando.utils.tasks import phab_trigger_repo_update

logger = logging.getLogger(__name__)


class AutomationWorker(Worker):
    """Worker to execute automation jobs.

    This worker runs `AutomationJob`s on enabled repositories.
    These jobs include a set of actions which are to be run on the repository,
    and then pushed to the destination repo.
    """

    job_type = AutomationJob

    worker_type = WorkerType.AUTOMATION

    def skip_checks(self, job: AutomationJob, new_commits: list[CommitData]) -> bool:
        return (
            job.has_one_action
            and job.actions.first().action_type == ActionTypeChoices.MERGE_ONTO
        ) or (new_commits and "a=release" in new_commits[-1].desc)

    @override
    def refresh_active_repos(self):
        """Override base functionality by not checking treestatus."""
        self.active_repos = self.enabled_repos

    @override
    def run_job(self, job: AutomationJob) -> bool:
        """Run an automation job."""
        repo = job.target_repo
        scm = repo.scm

        # Determine if a RelBranch should be used for the push.
        target_cset, push_target = job.resolve_push_target_from_relbranch(repo)

        with (
            scm.for_push(job.requester_email),
            PushLogForRepo(repo, job.requester_email, branch=push_target) as pushlog,
        ):
            try:
                pre_head_ref = self.update_repo(repo, job, scm, target_cset=target_cset)
            except PermanentFailureException:
                return True
            except TemporaryFailureException:
                return False

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

            new_commits = scm.describe_local_changes(base_cset=pre_head_ref)

            if not self.skip_checks(job, new_commits) and repo.hooks_enabled:
                patch_helpers = repo.scm.get_patch_helpers_for_commits(new_commits)
                landing_checks = LandingChecks(job.requester_email, repo.name)
                try:
                    check_errors = landing_checks.run(repo.hooks, patch_helpers)
                except Exception as exc:
                    message = "Unexpected error while performing landing checks."
                    logger.exception(message)
                    job.transition_status(
                        JobAction.FAIL,
                        message=f"{message}\n{exc}",
                    )
                    return True  # Do not try again, this is a permanent failure.

                if check_errors:
                    message = "Some checks weren't successful:\n" + "\n".join(
                        check_errors
                    )
                    logger.exception(message)
                    job.transition_status(
                        JobAction.FAIL,
                        message=message,
                    )
                    return True  # Do not try again, this is a permanent failure.

            # We need to add the commits to the pushlog _before_ pushing, so we can
            # compare the current stack to the last upstream.
            # We'll only confirm them if the push succeeds.
            for commit in new_commits:
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
                    push_target=push_target,
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
                    f"encountered while pushing to {repo_push_info}: {e}"
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

        # If any of the new commits are reverts, comment on the reverted PRs.
        revert_commits = CommitData.find_revert_commits(new_commits)
        if revert_commits:
            github_client = GitHubAPIClient(repo.push_path)
            reverts = {
                commit.hash: find_reverted_prs(commit, scm, github_client)
                for commit in revert_commits
            }
            for commit_hash, pull_requests in reverts:
                comment_on_reverted_prs(pull_requests, commit_hash)

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        if repo.phab_identifier:
            self.call_task(phab_trigger_repo_update, repo.phab_identifier)

        return True


def find_reverted_prs(
    revert_commit: CommitData,
    scm: AbstractSCM,
    github_client: GitHubAPIClient,
) -> list[PullRequest]:
    """Return PR numbers named in a revert commit that should be commented on."""
    original_commits = {
        commit_hash: scm.describe_commit(commit_hash).desc
        for commit_hash in revert_commit.reverted_commit_hashes()
    }
    reverted_prs = [
        get_reverted_pr(commit_hash, commit_message, github_client)
        for commit_hash, commit_message in original_commits.items()
    ]
    return [pr for pr in reverted_prs if pr]


def get_reverted_pr(
    original_commit_message: str,
    original_commit_hash: str,
    github_client: GitHubAPIClient,
) -> PullRequest | None:
    """Return the PR to comment on for one reverted commit, or `None` to skip it."""

    pr_url_data = PullRequest.parse_pr_url(original_commit_message)
    if not pr_url_data:
        logger.debug(
            f"Skipping commit {original_commit_hash}: reverted commit has no "
            f"parseable PR URL in commit message."
        )
        return None

    pr_number = pr_url_data["number"]
    pr_owner = pr_url_data["owner"]
    pr_repo = pr_url_data["repo"]
    expected_owner = github_client.repo_owner
    expected_repo = github_client.repo_name

    if pr_owner != expected_owner or pr_repo != expected_repo:
        logger.warning(
            f"Skipping commit {original_commit_hash} because PR URL in commit message "
            f"[{original_commit_message}] points to unexpected repo: {pr_owner}/{pr_repo}, "
            f"but automation worker expected PRs to be from {expected_owner}/{expected_repo}."
        )
        return None

    try:
        pr_to_revert = github_client.build_pull_request(pr_number)
    except Exception:
        logger.exception(
            f"Skipping commit {original_commit_hash}: PR #{pr_number} could not "
            f"be found via the GitHub API."
        )
        return None
    return pr_to_revert


def comment_on_reverted_prs(reverted_prs: list[PullRequest], commit_hash: str):
    """Post a 'has been reverted' comment on each reverted pull request."""
    for pr in reverted_prs:
        pr.add_comment(
            f"This pull request has been reverted by commit {commit_hash}.",
        )
