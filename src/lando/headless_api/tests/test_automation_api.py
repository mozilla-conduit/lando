import base64
import datetime
import itertools
import json
import secrets
import subprocess
import time
import unittest.mock as mock
from pathlib import Path
from typing import Callable

import pytest
from django.contrib.auth.hashers import check_password

from lando.api.legacy.workers.automation_worker import AutomationWorker
from lando.api.tests.mocks import TreeStatusDouble
from lando.conftest import FAILING_CHECK_TYPES
from lando.headless_api.api import (
    AutomationAction,
    AutomationJob,
)
from lando.headless_api.models.tokens import ApiToken
from lando.main.models import JobStatus
from lando.main.scm import SCM_TYPE_GIT, PatchConflict
from lando.main.scm.exceptions import SCMInternalServerError
from lando.main.tests.test_git import _create_git_commit
from lando.pushlog.models import Push


@pytest.fixture
def automation_job() -> Callable:
    """Create an automation job from the specified actions."""

    def create_automation_job(
        actions: list[dict], **job_args
    ) -> tuple[AutomationJob, list[AutomationAction]]:
        job = AutomationJob.objects.create(**job_args)

        automation_actions = []
        for idx, action in enumerate(actions):
            action_type = action.get("action", "badtype")

            automation_action = AutomationAction.objects.create(
                job_id=job, action_type=action_type, data=action, order=idx
            )

            automation_actions.append(automation_action)

        return job, automation_actions

    return create_automation_job


@pytest.mark.django_db
def test_auth_missing_user_agent(client, headless_user, automation_job):
    user, token = headless_user

    # Create a job and actions
    job, _actions = automation_job(
        status=JobStatus.SUBMITTED, actions=[{"content": "test"}]
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 401, "Missing `User-Agent` should result in 401."
    assert response.json() == {"details": "`User-Agent` header is required."}


@pytest.mark.django_db
def test_auth_user_agent_bad_format(client, headless_user, automation_job):
    user, token = headless_user

    # Create a job and actions
    job, _actions = automation_job(
        status=JobStatus.SUBMITTED, actions=[{"content": "test"}]
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "testuser@example.org",
        },
    )

    assert response.status_code == 401, "Missing `User-Agent` should result in 401."
    assert response.json() == {"details": "Incorrect `User-Agent` format."}


@pytest.mark.django_db
def test_auth_missing_authorization_header(client, headless_user, automation_job):
    # Create a job and actions
    job, _actions = automation_job(
        status=JobStatus.SUBMITTED, actions=[{"content": "test"}]
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
        },
    )

    assert response.status_code == 401, "Missing `User-Agent` should result in 401."
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.django_db
def test_auth_invalid_token(client, headless_user, automation_job):
    # Create a job and actions
    job, _actions = automation_job(
        status=JobStatus.SUBMITTED, actions=[{"content": "test"}]
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "Authorization": "Bearer api-bad-key",
            "User-Agent": "Lando-User/testuser@example.org",
        },
    )

    assert (
        response.status_code == 401
    ), "Invalid API key should result in 401 status code."
    assert response.json() == {"details": "Token api-bad-key was not found."}


@pytest.mark.django_db
def test_automation_job_create_bad_repo(client, headless_user):
    user, token = headless_user

    body = {
        "actions": [
            {
                "action": "add-commit",
                "content": "TESTIN123",
                "patch_format": "git-format-patch",
            },
        ],
    }
    response = client.post(
        "/api/repo/blah",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 404, "Unknown repo should respond with 404."
    assert response.json() == {"details": "Repo blah does not exist."}


@pytest.mark.django_db
def test_automation_job_empty_actions(client, headless_user):
    user, token = headless_user

    body = {
        "actions": [],
    }
    response = client.post(
        "/api/repo/blah",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 422
    ), "Empty `actions` should result in validation error."


@pytest.mark.parametrize(
    "bad_action,reason",
    (
        (
            {
                "action": "bad-action",
                "content": "TESTIN123",
                "patch_format": "git-format-patch",
            },
            "`bad-action` is an invalid action name.",
        ),
        (
            {
                "action": "add-commit",
                "content": {"test": 123},
                "patch_format": "git-format-patch",
            },
            "`content` should be a `str`.",
        ),
        (
            {
                "action": "add-commit",
                "content": 1,
                "patch_format": "git-format-patch",
            },
            "`content` should be a `str`.",
        ),
    ),
)
@pytest.mark.django_db
def test_automation_job_create_bad_action(bad_action, reason, client, headless_user):
    user, token = headless_user

    body = {
        "actions": [bad_action],
    }
    response = client.post(
        "/api/repo/blah",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 422
    ), f"Improper `actions` JSON schema should return 422 status: {reason}"


@pytest.mark.django_db
def test_automation_job_create_repo_automation_disabled(
    client,
    headless_user,
    repo_mc,
):
    user, token = headless_user

    repo_mc(
        scm_type=SCM_TYPE_GIT,
        automation_enabled=False,
    )

    body = {
        "actions": [
            # Set `content` to a string integer to test order is preserved.
            {
                "action": "add-commit",
                "content": "0",
                "patch_format": "git-format-patch",
            },
            {
                "action": "add-commit",
                "content": "1",
                "patch_format": "git-format-patch",
            },
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central-git",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 400
    ), "Automation disabled for repo should return `400 Bad Request` status."
    assert (
        response.json()["details"]
        == "Repo mozilla-central-git is not enabled for automation."
    ), "Details should indicate automation API is disabled for repo."


@pytest.mark.django_db
def test_automation_job_create_user_automation_disabled(
    client, headless_user, repo_mc, headless_permission
):
    user, token = headless_user

    # Disable automation enabled for user.
    user.user_permissions.remove(headless_permission)
    user.save()
    user.profile.save()

    repo_mc(
        scm_type=SCM_TYPE_GIT,
        automation_enabled=True,
    )

    # Send a valid request.
    body = {
        "actions": [
            {
                "action": "add-commit",
                "content": "0",
                "patch_format": "git-format-patch",
            },
            {
                "action": "add-commit",
                "content": "1",
                "patch_format": "git-format-patch",
            },
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central-git",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 401
    ), "User disabled for automation should return 401 status code."
    response_json = response.json()
    assert (
        response_json["details"]
        == "User testuser@example.org is not permitted to make automation changes."
    )


def is_isoformat_timestamp(date_string: str) -> bool:
    """Return `True` if `date_string` is an ISO format datetime string."""
    try:
        datetime.datetime.fromisoformat(date_string)
        return True
    except ValueError:
        return False


@pytest.mark.django_db
def test_automation_job_create_api(client, repo_mc, headless_user):
    user, token = headless_user

    repo_mc(
        scm_type=SCM_TYPE_GIT,
        automation_enabled=True,
    )

    body = {
        "actions": [
            # Set `content` to a string integer to test order is preserved.
            {
                "action": "add-commit",
                "content": "0",
                "patch_format": "git-format-patch",
            },
            {
                "action": "add-commit",
                "content": "1",
                "patch_format": "git-format-patch",
            },
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central-git",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 202
    ), "Successful submission should result in `202 Accepted` status code."

    response_json = response.json()

    job_id = response_json["job_id"]
    assert isinstance(job_id, int), "Job ID should be returned as an `int`."

    assert response_json["status_url"] == f"https://lando.test/api/job/{job_id}"
    assert response_json["message"] == "Job is in the SUBMITTED state."
    assert response_json["status"] == "SUBMITTED"
    assert is_isoformat_timestamp(
        response_json["created_at"]
    ), "Response should include an ISO formatted creation timestamp."

    job = AutomationJob.objects.get(id=job_id)

    for index, action in enumerate(job.actions.all()):
        assert action.data["content"] == str(
            index
        ), "Actions should be retrieved in order of submission."


@pytest.mark.django_db
def test_automation_job_create_commit_request(client, repo_mc, headless_user):
    user, token = headless_user

    repo = repo_mc(SCM_TYPE_GIT)
    body = {
        "actions": [
            {
                "action": "create-commit",
                "commitmsg": "No bug: test commit message",
                "date": "2025-04-22T18:30:27.786900Z",
                "author": "Test User <test@example.com>",
                "diff": "diff --git",
            }
        ],
    }
    response = client.post(
        f"/api/repo/{repo.name}",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 202
    ), "Successful submission should result in `202 Accepted` status code."

    job_id = response.json()["job_id"]
    job = AutomationJob.objects.get(id=job_id)
    action = job.actions.all()[0]

    assert (
        action.data["date"] == "2025-04-22T18:30:27.786900Z"
    ), "`date` field should be serialized properly."


@pytest.mark.django_db
def test_get_job_status_not_found(client, headless_user):
    user, token = headless_user
    response = client.get(
        "/api/job/12345",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )
    assert (
        response.status_code == 404
    ), "API should respond with a 404 for non-existent job ID."


@pytest.mark.parametrize(
    "status,message",
    (
        (JobStatus.SUBMITTED, "Job is in the SUBMITTED state."),
        (JobStatus.IN_PROGRESS, "Job is in the IN_PROGRESS state."),
        (JobStatus.DEFERRED, "Job is in the DEFERRED state."),
        (JobStatus.FAILED, "Job is in the FAILED state."),
        (JobStatus.LANDED, "Job is in the LANDED state."),
        (JobStatus.CANCELLED, "Job is in the CANCELLED state."),
    ),
)
@pytest.mark.django_db
def test_get_job_status(
    status, message, client, headless_user, automation_job, repo_mc
):
    user, token = headless_user
    repo = repo_mc(SCM_TYPE_GIT)

    # Create a job and actions
    job, _actions = automation_job(
        status=status, actions=[{"content": "test"}], target_repo=repo
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 200
    ), "Response code should be 200 when status is retrieved successfully."

    response_data = response.json()

    assert response_data["job_id"] == job.id
    assert (
        response_data["message"] == message
    ), "Response message should align with current job status."
    # TODO test a few more things? formatting?


@pytest.fixture
def automation_worker(landing_worker_instance):
    worker = landing_worker_instance(
        name="automation-worker-git",
        scm=SCM_TYPE_GIT,
    )
    return AutomationWorker(worker)


@pytest.mark.django_db
def test_automation_job_add_commit_success_git(
    treestatusdouble,
    automation_worker,
    repo_mc,
    mock_phab_trigger_repo_update_apply_async,
    git_patch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a job and actions
    job, _actions = automation_job(
        actions=[
            {
                "action": "add-commit",
                "content": git_patch(),
                "patch_format": "git-format-patch",
            },
            {
                "action": "add-commit",
                "content": git_patch(
                    1
                ),  # Patch with non-UTF8 binary in text-like file.
                "patch_format": "git-format-patch",
            },
        ],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    scm.push = mock.MagicMock()

    assert automation_worker.run_job(job)

    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."

    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False, "tags": []}


@pytest.mark.django_db
def test_automation_job_add_commit_base64_success_git(
    treestatusdouble,
    automation_worker,
    repo_mc,
    mock_phab_trigger_repo_update_apply_async,
    git_patch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a valid patch and base64-encode it.
    patch_text = git_patch()
    patch_bytes = patch_text.encode("utf-8")
    patch_b64 = base64.b64encode(patch_bytes).decode("ascii")

    # Create a job and the new base64 commit action.
    job, _actions = automation_job(
        actions=[
            {
                "action": "add-commit-base64",
                "content": patch_b64,
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    scm.push = mock.MagicMock()

    assert automation_worker.run_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False, "tags": []}
    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."


@pytest.mark.django_db
def test_automation_job_add_commit_fail(
    repo_mc,
    treestatusdouble,
    automation_worker,
    mock_phab_trigger_repo_update_apply_async,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a job and actions
    job, _actions = automation_job(
        actions=[
            {
                "action": "add-commit",
                "content": "FAIL",
                "patch_format": "git-format-patch",
            },
        ],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    scm.push = mock.MagicMock()

    assert not automation_worker.run_job(job)
    assert job.status == JobStatus.FAILED, "Automation job should fail."
    assert scm.push.call_count == 0


@pytest.mark.django_db
def test_automation_job_create_commit_success(
    repo_mc,
    treestatusdouble,
    automation_worker,
    mock_phab_trigger_repo_update_apply_async,
    get_failing_check_diff,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a job and actions
    job, _actions = automation_job(
        actions=[
            {
                "action": "create-commit",
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: commit success",
                "date": 0,
                "diff": get_failing_check_diff("valid"),
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    scm.push = mock.MagicMock()

    assert automation_worker.run_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == repo.url
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False, "tags": []}
    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."


@pytest.mark.parametrize(
    "bad_action_type,hooks_enabled",
    # We make a cross-product of all the SCM and all the bad actions.
    itertools.product(
        FAILING_CHECK_TYPES,
        (True, False),
    ),
)
@pytest.mark.django_db
def test_automation_job_create_commit_failed_check(
    repo_mc,
    treestatusdouble,
    automation_worker,
    mock_phab_trigger_repo_update_apply_async,
    get_failing_check_action_reason: Callable,
    bad_action_type: str,
    hooks_enabled: bool,
    get_failing_check_diff: Callable,
    extract_email: Callable,
    automation_job: Callable,
):
    bad_action, reason = get_failing_check_action_reason(bad_action_type)

    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    repo.hooks_enabled = hooks_enabled

    author_email = extract_email(bad_action["author"])

    # Create a job and actions
    job, _actions = automation_job(
        actions=[bad_action],
        status=JobStatus.SUBMITTED,
        requester_email=author_email,
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    scm.push = mock.MagicMock()

    assert automation_worker.run_job(job), "Job indicated that it should be retried"

    if hooks_enabled:
        assert (
            job.status == JobStatus.FAILED
        ), f"Job unexpectedly succeeded for commit `{bad_action['commitmsg']}`"
        assert reason in job.error, "Expected job failure reason was not found"
    else:
        assert (
            job.status == JobStatus.LANDED
        ), "Job did not succeed despite disabled hooks."


@pytest.fixture
def get_failing_check_action_reason(get_failing_check_commit_reason):
    def failed_check_action_factory(name: str) -> tuple[dict, str] | None:
        """Factory providing a check-failing action, and the expected failure reason.

        See FAILING_CHECK_TYPES for the list of commit types available for request.

        For convenience, a "valid" case is also available.
        """
        # We simply take a failing commit metadata, and add the rest of the
        # AutomationAction payload.
        action_reason = get_failing_check_commit_reason(name)
        action_reason[0]["action"] = "create-commit"
        action_reason[0]["date"] = 0
        return action_reason

    return failed_check_action_factory


@pytest.mark.django_db
def test_automation_job_create_commit_failed_check_override(
    repo_mc,
    treestatusdouble,
    automation_worker,
    mock_phab_trigger_repo_update_apply_async: mock.Mock,
    get_failing_check_action_reason: Callable,
    get_failing_check_diff,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    no_bug_action_data = get_failing_check_action_reason("nobug")[0]
    override_action_data = {
        "action": "create-commit",
        "author": "Test User <test@example.com>",
        "commitmsg": "IGNORE BAD COMMIT MESSAGES",
        "date": 0,
        "diff": get_failing_check_diff("valid2"),
    }

    # Create a job and _all_ invalid actions
    job, _actions = automation_job(
        actions=[no_bug_action_data, override_action_data],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    scm.push = mock.MagicMock()

    assert automation_worker.run_job(job), "Job indicated that it should be retried"
    assert job.status == JobStatus.LANDED, f"Job failed despite overrides: {job.error}"


@pytest.mark.django_db
def test_automation_job_create_commit_failed_check_unchecked(
    repo_mc,
    treestatusdouble,
    automation_worker,
    mock_phab_trigger_repo_update_apply_async: mock.Mock,
    get_failing_check_action_reason: Callable,
    get_failing_check_diff,
    automation_job,
    monkeypatch,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    no_bug_action_data = get_failing_check_action_reason("nobug")[0]
    release_action_data = {
        "action": "create-commit",
        "author": "Test User <test@example.com>",
        "commitmsg": "some commit a=release",
        "date": 0,
        "diff": get_failing_check_diff("valid2"),
    }

    automation_worker.worker_instance.applicable_repos.add(repo)
    scm.push = mock.MagicMock()

    # Create a job with an invalid action.
    job, _actions = automation_job(
        actions=[no_bug_action_data],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    mock_run_automation_checks = mock.MagicMock()
    monkeypatch.setattr(
        automation_worker, "run_automation_checks", mock_run_automation_checks
    )
    automation_worker.run_job(job)
    assert mock_run_automation_checks.call_count == 1

    # Create the same job with an invalid action and a commit with release override.
    job, _actions = automation_job(
        actions=[no_bug_action_data, release_action_data],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    mock_run_automation_checks = mock.MagicMock()
    monkeypatch.setattr(
        automation_worker, "run_automation_checks", mock_run_automation_checks
    )
    automation_worker.run_job(job)
    assert mock_run_automation_checks.call_count == 0


@pytest.mark.django_db
def test_automation_job_create_commit_patch_conflict(
    repo_mc,
    treestatusdouble,
    automation_worker,
    monkeypatch,
    get_failing_check_diff,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)

    job, _actions = automation_job(
        actions=[
            {
                "action": "create-commit",
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: conflict commit",
                "date": 0,
                "diff": get_failing_check_diff("valid"),
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    def raise_conflict(*args, **kwargs):
        raise PatchConflict("Conflict in patch")

    monkeypatch.setattr(repo.scm, "apply_patch", raise_conflict)

    assert not automation_worker.run_job(job)

    assert "Merge conflict while creating commit" in job.error
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED


def _create_split_branches_for_merge(
    request, scm, repo_path, main_branch="main", feature_branch="feature"
):
    subprocess.run(["git", "switch", main_branch], cwd=repo_path, check=True)
    main_file = _create_git_commit(request, repo_path)
    main_commit = scm.head_ref()

    subprocess.run(
        ["git", "switch", "-c", feature_branch, "HEAD^"], cwd=repo_path, check=True
    )
    feature_file = _create_git_commit(request, repo_path)
    feature_commit = scm.head_ref()

    subprocess.run(["git", "switch", main_branch], cwd=repo_path, check=True)

    return main_commit, main_file, feature_commit, feature_file


@pytest.mark.parametrize("strategy", [None, "ours", "theirs"])
@pytest.mark.django_db
def test_automation_job_merge_onto_success_git(
    strategy,
    repo_mc,
    treestatusdouble,
    automation_worker,
    monkeypatch,
    request,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm
    scm.push = mock.MagicMock()

    # Create a repo with diverging history
    main_commit, main_file, feature_commit, feature_file = (
        _create_split_branches_for_merge(request, scm, repo.system_path)
    )

    job, _actions = automation_job(
        actions=[
            {
                "action": "merge-onto",
                "commit_message": f"No bug: Merge test with strategy {strategy}",
                "strategy": strategy,
                "target": feature_commit,
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    assert automation_worker.run_job(job)
    assert job.status == JobStatus.LANDED, f"Job unexpectedly failed: {job.error}"
    assert scm.push.called
    assert len(job.landed_commit_id) == 40


@pytest.mark.django_db
def test_automation_job_merge_onto_fast_forward_git(
    repo_mc,
    treestatusdouble,
    automation_worker,
    request,
    monkeypatch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm
    scm.push = mock.MagicMock()

    repo_path = Path(repo.system_path)

    # Start on main, make a commit.
    subprocess.run(["git", "switch", "main"], cwd=repo_path, check=True)
    _create_git_commit(request, repo_path)

    # Create feature branch from main, add another commit.
    subprocess.run(["git", "switch", "-c", "feature"], cwd=repo_path, check=True)
    _create_git_commit(request, repo_path)
    feature_sha = scm.head_ref()

    # Return to base (fast-forward target).
    subprocess.run(["git", "switch", "main"], cwd=repo_path, check=True)

    job, _actions = automation_job(
        actions=[
            {
                "action": "merge-onto",
                "commit_message": "Fast-forward merge test",
                "strategy": None,
                "target": feature_sha,
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    mock_run_automation_checks = mock.MagicMock()
    monkeypatch.setattr(
        automation_worker, "run_automation_checks", mock_run_automation_checks
    )
    assert automation_worker.run_job(job)
    assert mock_run_automation_checks.call_count == 0
    assert job.status == JobStatus.LANDED

    head_ref = scm.head_ref()
    assert head_ref == feature_sha, "New `head_ref` should match the `feature_sha`."

    # Confirm only one parent (not a merge commit)
    parents = (
        subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", head_ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .split()
    )

    assert (
        len(parents) == 2
    ), f"Expected fast-forward commit with 1 parent, got: {parents}"


@pytest.mark.django_db
def test_automation_job_merge_onto_fail(
    repo_mc,
    treestatusdouble,
    automation_worker,
    monkeypatch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)

    job, _actions = automation_job(
        actions=[
            {
                "action": "merge-onto",
                "commit_message": "bad merge",
                "strategy": None,
                "target": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    assert not automation_worker.run_job(job), f"Job should not complete."
    assert job.status == JobStatus.FAILED
    assert "Aborting, could not perform `merge-onto`" in job.error


@pytest.mark.django_db
def test_automation_job_tag_success_git_tip_commit(
    repo_mc,
    treestatusdouble,
    automation_worker,
    request,
    monkeypatch,
    normal_patch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    head_ref = scm.head_ref()

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job, _actions = automation_job(
        actions=[
            {
                "action": "tag",
                "name": tag_name,
                "target": head_ref,
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    assert automation_worker.run_job(job)
    assert job.status == JobStatus.LANDED

    # Tag should be on the most recent commit.
    expected_commit = scm.head_ref()

    # now compare to the tag
    tag_commit = subprocess.run(
        ["git", "rev-list", "-n", "1", tag_name],
        cwd=repo.system_path,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()

    assert tag_commit == expected_commit


@pytest.mark.django_db
def test_automation_job_tag_retag_success_git(
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,  # pyright: ignore[reportUnusedParameter] Mock with side-effect
    active_mock: Callable,
    automation_worker: Callable,
    request: pytest.FixtureRequest,
    automation_job: Callable,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    active_mock(scm, "push")
    scm.push.side_effect = [
        SCMInternalServerError("Some Github error", "403"),
        scm.push.side_effect,
    ]

    head_ref = scm.head_ref()

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job, _actions = automation_job(
        actions=[
            {
                "action": "tag",
                "name": tag_name,
                "target": head_ref,
            }
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    assert not automation_worker.run_job(
        job
    ), "The automation job should not have succeeded the first time."
    assert (
        job.status == JobStatus.DEFERRED
    ), "Job should have been deferred on first push exception."
    assert "Some Github error" in job.error

    # This is an test for the current internal behaviour that a tags remains after a
    # failure, which the deferral should be able to work around.
    assert scm._git_run(
        "tag", "-l", tag_name, cwd=scm.path
    ), f"Though the job has failed, we would have expected a stray {tag_name} tag to still be present."

    assert automation_worker.run_job(job)
    assert job.status == JobStatus.LANDED, "Job should have landed on second run."

    # Tag should be on the most recent commit.
    expected_commit = scm.head_ref()

    # now compare to the tag
    tag_commit = subprocess.run(
        ["git", "rev-list", "-n", "1", tag_name],
        cwd=repo.system_path,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()

    assert tag_commit == expected_commit


@pytest.mark.django_db
def test_automation_job_tag_success_git_new_commit(
    repo_mc,
    treestatusdouble,
    automation_worker,
    request,
    monkeypatch,
    git_patch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job, _actions = automation_job(
        actions=[
            {
                "action": "add-commit",
                "content": git_patch(),
                "patch_format": "git-format-patch",
            },
            {"action": "tag", "name": tag_name, "target": None},
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    mock_run_automation_checks = mock.Mock(
        wraps=automation_worker.run_automation_checks
    )
    monkeypatch.setattr(
        automation_worker, "run_automation_checks", mock_run_automation_checks
    )
    assert automation_worker.run_job(job)
    assert mock_run_automation_checks.call_count == 1
    assert job.status == JobStatus.LANDED

    # Tag should be on the most recent commit.
    expected_commit = scm.head_ref()

    # now compare to the tag
    tag_commit = subprocess.run(
        ["git", "rev-list", "-n", "1", tag_name],
        cwd=repo.system_path,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()

    assert tag_commit == expected_commit


@pytest.mark.django_db
def test_automation_job_tag_failure_git(
    repo_mc,
    treestatusdouble,
    automation_worker,
    request,
    monkeypatch,
    git_patch,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job, _actions = automation_job(
        actions=[
            {
                "action": "add-commit",
                "content": git_patch(),
                "patch_format": "git-format-patch",
            },
            {"action": "tag", "name": tag_name, "target": "bad-target"},
        ],
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )

    automation_worker.worker_instance.applicable_repos.add(repo)

    assert not automation_worker.run_job(job)
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert "Aborting, could not perform `tag`, action #1" in job.error


@pytest.mark.django_db
def test_create_and_push_to_new_relbranch(
    client,
    treestatusdouble,
    repo_mc,
    automation_worker,
    headless_user,
    request,
    git_patch,
):
    user, token = headless_user
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a base commit (HEAD)
    subprocess.run(["git", "switch", "main"], cwd=repo.system_path)
    file_path = Path(repo.system_path) / "relbranch.txt"
    file_path.write_text("relbranch base\n")
    subprocess.run(["git", "add", "."], cwd=repo.system_path)
    subprocess.run(["git", "commit", "-m", "Base commit"], cwd=repo.system_path)
    base_commit = scm.head_ref()

    # Create a second commit to ensure the RelBranch can be created from any
    # arbitrary commit, not just the current head.
    head_file = Path(repo.system_path) / "head.txt"
    head_file.write_text("head\n")
    subprocess.run(["git", "add", "."], cwd=repo.system_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "HEAD commit"], cwd=repo.system_path, check=True
    )
    head_commit = scm.head_ref()

    assert base_commit != head_commit

    relbranch_name = "FIREFOX_ESR_999_99_X_RELBRANCH"

    body = {
        "relbranch": {
            "branch_name": relbranch_name,
            "commit_sha": base_commit,
        },
        "actions": [
            {
                "action": "add-commit",
                "content": git_patch(),
                "patch_format": "git-format-patch",
            },
        ],
    }

    # Submit the job
    response = client.post(
        f"/api/repo/{repo.name}",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Lando-User/testuser@example.org",
        },
    )

    job_id = response.json()["job_id"]
    job = AutomationJob.objects.get(id=job_id)

    automation_worker.worker_instance.applicable_repos.add(repo)
    assert automation_worker.run_job(job)

    assert job.status == JobStatus.LANDED
    assert job.landed_commit_id is not None

    # Fetch from `origin` so the remotes are available locally.
    subprocess.run(["git", "fetch", "origin"], cwd=repo.system_path, check=True)

    remote_branches = subprocess.run(
        ["git", "ls-remote", "--heads", repo.push_path, relbranch_name],
        cwd=repo.system_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (
        f"refs/heads/{relbranch_name}" in remote_branches
    ), "Push did not create a new RelBranch."

    local_sha = scm.head_ref()
    remote_sha = subprocess.run(
        ["git", "rev-parse", f"origin/{relbranch_name}"],
        cwd=repo.system_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert local_sha == remote_sha, "Remote relbranch SHA does not match local SHA."

    # Confirm new commit is based on base_commit
    current_commit = scm.head_ref()
    parents = (
        subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", current_commit],
            cwd=repo.system_path,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .split()
    )

    assert (
        base_commit in parents[1:]
    ), f"Expected base_commit {base_commit} to be parent of {current_commit}"

    # Confirm that 'head.txt' is not present on the relbranch
    tree_files = (
        subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", current_commit],
            cwd=repo.system_path,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )

    assert "head.txt" not in tree_files, "'head.txt' should not exist on the relbranch"

    # Confirm `Push` has the correct branch name.
    pushes = Push.objects.all()
    assert len(pushes) == 1
    assert (
        pushes[0].branch == relbranch_name
    ), f"Completed push should point to `{relbranch_name}`."


@pytest.mark.django_db
def test_push_to_existing_relbranch(
    client,
    treestatusdouble,
    repo_mc,
    automation_worker,
    headless_user,
    request,
    git_patch,
):
    user, token = headless_user
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    relbranch_name = "FIREFOX_ESR_999_99_X_RELBRANCH"

    # Create branch manually and push it to simulate an existing remote relbranch
    subprocess.run(
        ["git", "switch", "-c", relbranch_name], cwd=repo.system_path, check=True
    )
    file_path = Path(repo.system_path) / "existing-relbranch.txt"
    file_path.write_text("existing relbranch base\n")
    subprocess.run(["git", "add", "."], cwd=repo.system_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial relbranch commit"],
        cwd=repo.system_path,
        check=True,
    )
    subprocess.run(
        ["git", "push", "origin", relbranch_name], cwd=repo.system_path, check=True
    )

    subprocess.run(["git", "switch", "main"], cwd=repo.system_path, check=True)

    body = {
        "relbranch": {"branch_name": relbranch_name},
        "actions": [
            {
                "action": "add-commit",
                "content": git_patch(),
                "patch_format": "git-format-patch",
            },
        ],
    }

    # Submit the job
    response = client.post(
        f"/api/repo/{repo.name}",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Lando-User/testuser@example.org",
        },
    )

    job_id = response.json()["job_id"]
    job = AutomationJob.objects.get(id=job_id)

    automation_worker.worker_instance.applicable_repos.add(repo)
    assert automation_worker.run_job(job)

    assert job.status == JobStatus.LANDED
    assert job.landed_commit_id is not None

    # Fetch updated remote refs
    subprocess.run(["git", "fetch", "origin"], cwd=repo.system_path, check=True)

    # Ensure remote branch exists
    remote_branches = subprocess.run(
        ["git", "ls-remote", "--heads", repo.push_path, relbranch_name],
        cwd=repo.system_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (
        f"refs/heads/{relbranch_name}" in remote_branches
    ), "Expected relbranch to exist on remote after push."

    # Compare local HEAD to remote relbranch SHA
    local_sha = scm.head_ref()
    remote_sha = subprocess.run(
        ["git", "rev-parse", f"origin/{relbranch_name}"],
        cwd=repo.system_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert local_sha == remote_sha, "Remote relbranch SHA does not match local SHA."

    # Confirm `Push` has the correct branch name.
    pushes = Push.objects.all()
    assert len(pushes) == 1
    assert (
        pushes[0].branch == relbranch_name
    ), f"Completed push should point to `{relbranch_name}`."


@pytest.mark.parametrize(
    "relbranch_specifier,expected_target_cset,expected_push_target",
    [
        # Case 1: No relbranch_specifier
        (None, None, "default_target"),
        # Case 2: Only branch_name
        (
            {"branch_name": "FIREFOX_ESR_123_45_X_RELBRANCH"},
            "FIREFOX_ESR_123_45_X_RELBRANCH",
            "FIREFOX_ESR_123_45_X_RELBRANCH",
        ),
        # Case 3: branch_name + commit_sha
        (
            {
                "branch_name": "FIREFOX_ESR_123_45_X_RELBRANCH",
                "commit_sha": "blah1234",
            },
            "blah1234",
            "FIREFOX_ESR_123_45_X_RELBRANCH",
        ),
    ],
)
@pytest.mark.django_db
def test_resolve_push_target_from_relbranch(
    repo_mc,
    relbranch_specifier,
    expected_target_cset,
    expected_push_target,
    automation_job,
):
    repo = repo_mc(SCM_TYPE_GIT)

    # Set the push target to a default for the no-relbranch case.
    repo.push_target = "default_target"

    job, _actions = automation_job(
        actions=[],
        status="SUBMITTED",
        requester_email="user@example.com",
        target_repo=repo,
    )

    if relbranch_specifier:
        job.relbranch_name = relbranch_specifier.get("branch_name")
        job.relbranch_commit_sha = relbranch_specifier.get("commit_sha")

    target_cset, push_target = job.resolve_push_target_from_relbranch(repo)

    assert target_cset == expected_target_cset, "Expected checkout target is incorrect."
    assert push_target == expected_push_target, "Expected push target is incorrect."


@pytest.mark.django_db
def test_token_generation_security(headless_user):
    user, token = headless_user

    # Retrieve the stored token object.
    token_obj = ApiToken.objects.get(user=user)

    # Verify that the stored token prefix equals the first 8 characters of the token.
    assert token_obj.token_prefix == token[:8]

    # Ensure that the stored hash is not simply the raw token.
    assert token_obj.token_hash != token

    # Use Django's check_password to verify that the hash matches the raw token.
    assert check_password(token, token_obj.token_hash)


@pytest.mark.django_db
def test_valid_token_verification(headless_user):
    user, token = headless_user

    assert (
        ApiToken.verify_token(token).user == user
    ), "verify_token should return the user for a valid token."


@pytest.mark.django_db
def test_invalid_token_prefix_invalid(headless_user):
    user, token = headless_user

    first_char = token[0]

    new_char = "a" if first_char != "a" else "b"

    # Modify the token prefix so it is invalid.
    invalid_token = new_char + token[1:]

    # verify_token should raise a `ValueError` for bad token.
    with pytest.raises(ValueError):
        ApiToken.verify_token(invalid_token)


@pytest.mark.django_db
def test_invalid_token_prefix_valid(headless_user):
    user, token = headless_user

    last_char = token[-1]

    new_char = "a" if last_char != "a" else "b"

    # Modify the end of the token to confirm a found prefix must still
    # match the hash/salt.
    invalid_token = token[:-1] + new_char

    # verify_token should raise a `ValueError` for bad token.
    with pytest.raises(ValueError):
        ApiToken.verify_token(invalid_token)


@pytest.mark.django_db
def test_token_prefix_collision(monkeypatch, headless_user):
    """Force a scenario where two tokens share the same prefix.

    Although extremely unlikely in production, this ensures our filtering plus
    hash-check strategy works.
    """
    user, token = headless_user

    original_token_hex = secrets.token_hex

    def fake_token_hex(nbytes=20):
        # Force a constant prefix ("deadbeef")
        # while keeping the rest of the token random.
        return "deadbeef" + original_token_hex(nbytes=nbytes)[8:]

    monkeypatch.setattr(secrets, "token_hex", fake_token_hex)

    token1 = ApiToken.create_token(user)
    token2 = ApiToken.create_token(user)

    # Even if both tokens share the same prefix, each should verify correctly.
    assert (
        ApiToken.verify_token(token1).user == user
    ), "First token with common prefix should return headless user."
    assert (
        ApiToken.verify_token(token2).user == user
    ), "Second token with common prefix should return headless user."


@pytest.mark.django_db
def test_get_repo_info_success(client, headless_user, repo_mc):
    user, token = headless_user

    repo = repo_mc(SCM_TYPE_GIT)

    response = client.get(
        f"/api/repoinfo/{repo.short_name}",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert (
        response.status_code == 200
    ), "`repoinfo` should return 200 for successful response."

    response_json = response.json()
    assert response_json["repo_url"] == repo.url, "`repo_url` does not match expected."
    assert (
        response_json["branch_name"] == repo.default_branch
    ), "`branch_name` does not match expected."
    assert (
        response_json["scm_level"] == "scm_level_3"
    ), "`scm_level` does not match expected."


@pytest.mark.django_db
def test_get_repo_info_not_found(client, headless_user):
    user, token = headless_user

    response = client.get(
        "/api/repoinfo/nonexistent-repo",
        headers={
            "User-Agent": "Lando-User/testuser@example.org",
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 404, "Non-existent repo should return 404."
    assert response.json() == {
        "details": "Repo with short name nonexistent-repo does not exist."
    }


@pytest.mark.django_db
def test_automation_job_processing(automation_job):
    # Create a job.
    job, _actions = automation_job(status=JobStatus.SUBMITTED, actions=[])

    with job.processing():
        time.sleep(1)

    # Query for the job to ensure we inspect the result as it exists in the DB.
    job_from_db = AutomationJob.objects.get(id=job.id)
    assert (
        job_from_db.duration_seconds > 0
    ), "`processing` should set and save the job duration."
