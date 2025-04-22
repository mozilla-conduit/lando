import datetime
import json
from os import wait
import secrets
import subprocess
import unittest.mock as mock
from pathlib import Path

import pytest
from django.contrib.auth.hashers import check_password

from lando.api.legacy.workers.automation_worker import AutomationWorker
from lando.api.tests.test_hg import _create_hg_commit
from lando.headless_api.api import (
    AutomationAction,
    AutomationJob,
)
from lando.headless_api.models.tokens import ApiToken
from lando.main.models import SCM_LEVEL_3, Repo
from lando.main.models.landing_job import JobStatus
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.scm.exceptions import PatchConflict
from lando.main.tests.test_git import _create_git_commit


@pytest.mark.django_db
def test_auth_missing_user_agent(client, headless_user):
    user, token = headless_user

    # Create a job and actions
    job = AutomationJob.objects.create(status=JobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
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
def test_auth_user_agent_bad_format(client, headless_user):
    user, token = headless_user

    # Create a job and actions
    job = AutomationJob.objects.create(status=JobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
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
def test_auth_missing_authorization_header(client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=JobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
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
def test_auth_invalid_token(client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=JobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
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
                "patch_format": "hgexport",
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
                "patch_format": "hgexport",
            },
            "`bad-action` is an invalid action name.",
        ),
        (
            {
                "action": "add-commit",
                "content": {"test": 123},
                "patch_format": "hgexport",
            },
            "`content` should be a `str`.",
        ),
        (
            {
                "action": "add-commit",
                "content": 1,
                "patch_format": "hgexport",
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
    client, headless_user, hg_server, hg_clone
):
    user, token = headless_user

    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url=hg_server,
        required_permission=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
        system_path=hg_clone.strpath,
        automation_enabled=False,
    )

    body = {
        "actions": [
            # Set `content` to a string integer to test order is preserved.
            {"action": "add-commit", "content": "0", "patch_format": "hgexport"},
            {"action": "add-commit", "content": "1", "patch_format": "hgexport"},
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central",
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
        == "Repo mozilla-central is not enabled for automation."
    ), "Details should indicate automation API is disabled for repo."


@pytest.mark.django_db
def test_automation_job_create_user_automation_disabled(
    client, headless_user, hg_server, hg_clone, headless_permission
):
    user, token = headless_user

    # Disable automation enabled for user.
    user.user_permissions.remove(headless_permission)
    user.save()
    user.profile.save()

    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url=hg_server,
        required_permission=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
        system_path=hg_clone.strpath,
        automation_enabled=True,
    )

    # Send a valid request.
    body = {
        "actions": [
            {"action": "add-commit", "content": "0", "patch_format": "hgexport"},
            {"action": "add-commit", "content": "1", "patch_format": "hgexport"},
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central",
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
def test_automation_job_create_api(client, hg_server, hg_clone, headless_user):
    user, token = headless_user

    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url=hg_server,
        required_permission=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
        system_path=hg_clone.strpath,
        automation_enabled=True,
    )

    body = {
        "actions": [
            # Set `content` to a string integer to test order is preserved.
            {"action": "add-commit", "content": "0", "patch_format": "hgexport"},
            {"action": "add-commit", "content": "1", "patch_format": "hgexport"},
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central",
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
def test_get_job_status(status, message, client, headless_user):
    user, token = headless_user

    # Create a job and actions
    job = AutomationJob.objects.create(status=status)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
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
def hg_automation_worker(landing_worker_instance):
    worker = landing_worker_instance(
        name="automation-worker-hg",
        scm=SCM_TYPE_HG,
    )
    return AutomationWorker(worker)


@pytest.fixture
def git_automation_worker(landing_worker_instance):
    worker = landing_worker_instance(
        name="automation-worker-git",
        scm=SCM_TYPE_GIT,
    )
    return AutomationWorker(worker)


@pytest.fixture
def get_automation_worker(hg_automation_worker, git_automation_worker):
    workers = {
        SCM_TYPE_GIT: git_automation_worker,
        SCM_TYPE_HG: hg_automation_worker,
    }

    def _get_automation_worker(scm_type):
        return workers[scm_type]

    return _get_automation_worker


@pytest.mark.django_db
def test_automation_job_add_commit_success_hg(
    hg_server,
    hg_clone,
    treestatusdouble,
    hg_automation_worker,
    repo_mc,
    monkeypatch,
    normal_patch,
):
    repo = repo_mc(SCM_TYPE_HG)
    scm = repo.scm

    treestatusdouble.open_tree(repo.name)

    # Create a job and actions
    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={
            "action": "add-commit",
            "content": normal_patch(1),
            "patch_format": "hgexport",
        },
        order=0,
    )

    hg_automation_worker.worker_instance.applicable_repos.add(repo)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.automation_worker.AutomationWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    scm.push = mock.MagicMock()

    assert hg_automation_worker.run_automation_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == hg_server
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False, "tags": []}
    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."


PATCH_GIT_1 = """\
From 77a05b90d0d4eb7a75fa7acf052673e5dc36a20b Mon Sep 17 00:00:00 2001
From: Py Test <pytest@lando.example.net>
Date: Tue, 22 Apr 2025 02:02:55 +0000
Subject: [PATCH] add another file

---
 test.txt | 1 +
 1 file changed, 1 insertion(+)

diff --git a/test.txt b/test.txt
index 2a02d41..45e9938 100644
--- a/test.txt
+++ b/test.txt
@@ -1 +1,2 @@
 TEST
+adding another line
-- 
2.39.5
"""


@pytest.mark.django_db
def test_automation_job_add_commit_success_git(
    treestatusdouble, git_automation_worker, repo_mc, monkeypatch, normal_patch
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a job and actions
    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={
            "action": "add-commit",
            "content": PATCH_GIT_1,
            "patch_format": "git-format-patch",
        },
        order=0,
    )

    git_automation_worker.worker_instance.applicable_repos.add(repo)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.automation_worker.AutomationWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    scm.push = mock.MagicMock()

    assert git_automation_worker.run_automation_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False, "tags": []}
    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."


@pytest.mark.django_db
def test_automation_job_add_commit_fail(
    hg_server, hg_clone, repo_mc, treestatusdouble, hg_automation_worker, monkeypatch
):
    repo = repo_mc(SCM_TYPE_HG)
    scm = repo.scm

    # Create a job and actions
    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={"action": "add-commit", "content": "FAIL", "patch_format": "hgexport"},
        order=0,
    )

    hg_automation_worker.worker_instance.applicable_repos.add(repo)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.automation_worker.AutomationWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    scm.push = mock.MagicMock()

    assert not hg_automation_worker.run_automation_job(job)
    assert job.status == JobStatus.FAILED, "Automation job should fail."
    assert scm.push.call_count == 0


PATCH_DIFF = """
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()


@pytest.mark.parametrize("scm_type", (SCM_TYPE_HG, SCM_TYPE_GIT))
@pytest.mark.django_db
def test_automation_job_create_commit_success(
    scm_type,
    repo_mc,
    treestatusdouble,
    get_automation_worker,
    monkeypatch,
):
    repo = repo_mc(SCM_TYPE_HG)
    scm = repo.scm

    # Create a job and actions
    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="create-commit",
        data={
            "action": "create-commit",
            "author": "Test User <test@example.com>",
            "commitmsg": "add another file",
            "date": 0,
            "diff": PATCH_DIFF,
        },
        order=0,
    )

    automation_worker = get_automation_worker(scm_type)

    automation_worker.worker_instance.applicable_repos.add(repo)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.automation_worker.AutomationWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    scm.push = mock.MagicMock()

    assert automation_worker.run_automation_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == repo.url
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False, "tags": []}
    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."


@pytest.mark.parametrize("scm_type", (SCM_TYPE_HG, SCM_TYPE_GIT))
@pytest.mark.django_db
def test_automation_job_create_commit_patch_conflict(
    scm_type, repo_mc, treestatusdouble, get_automation_worker, monkeypatch
):
    repo = repo_mc(scm_type)
    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )

    AutomationAction.objects.create(
        job_id=job,
        action_type="create-commit",
        data={
            "action": "create-commit",
            "author": "Test User <test@example.com>",
            "commitmsg": "conflict commit",
            "date": 0,
            "diff": PATCH_DIFF,
        },
        order=0,
    )

    automation_worker = get_automation_worker(SCM_TYPE_GIT)
    automation_worker.worker_instance.applicable_repos.add(repo)

    def raise_conflict(*args, **kwargs):
        raise PatchConflict("Conflict in patch")

    monkeypatch.setattr(repo.scm, "apply_patch", raise_conflict)

    assert not automation_worker.run_automation_job(job)

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
    git_automation_worker,
    monkeypatch,
    request,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm
    scm.push = mock.MagicMock()

    # Create a repo with diverging history
    main_commit, main_file, feature_commit, feature_file = (
        _create_split_branches_for_merge(request, scm, repo.system_path)
    )

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="merge-onto",
        data={
            "action": "merge-onto",
            "commit_message": f"Merge test with strategy {strategy}",
            "strategy": strategy,
            "target": feature_commit,
        },
        order=0,
    )

    git_automation_worker.worker_instance.applicable_repos.add(repo)

    assert git_automation_worker.run_automation_job(job)
    assert job.status == JobStatus.LANDED
    assert scm.push.called
    assert len(job.landed_commit_id) == 40


@pytest.mark.parametrize("strategy", [None, "ours", "theirs"])
@pytest.mark.django_db
def test_automation_job_merge_onto_success_hg(
    strategy,
    repo_mc,
    treestatusdouble,
    hg_automation_worker,
    monkeypatch,
    request,
):
    repo = repo_mc(SCM_TYPE_HG)
    scm = repo.scm
    scm.push = mock.MagicMock()

    repo_path = Path(repo.system_path)

    # Create commits on a feature branch
    _create_hg_commit(request, repo_path)
    _create_hg_commit(request, repo_path)
    _create_hg_commit(request, repo_path)
    feature_commit = subprocess.run(
        ["hg", "log", "-r", ".", "-T", "{node}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Return to rev 0 and create mainline commits
    subprocess.run(["hg", "update", "--clean", "-r", "0"], cwd=repo_path, check=True)
    _create_hg_commit(request, repo_path)
    _create_hg_commit(request, repo_path)
    _create_hg_commit(request, repo_path)
    main_commit = subprocess.run(
        ["hg", "log", "-r", ".", "-T", "{node}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Push changes to hg_server before running the automation job
    subprocess.run(
        ["hg", "push", "-r", "draft()", repo.push_path, "-f"], cwd=repo_path, check=True
    )

    subprocess.run(
        ["hg", "update", "--clean", "-r", main_commit], cwd=repo.system_path, check=True
    )

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="merge-onto",
        data={
            "action": "merge-onto",
            "commit_message": f"merge test ({strategy})",
            "strategy": strategy,
            "target": feature_commit,
        },
        order=0,
    )

    hg_automation_worker.worker_instance.applicable_repos.add(repo)

    assert hg_automation_worker.run_automation_job(job)
    assert job.status == JobStatus.LANDED
    assert scm.push.called
    assert len(job.landed_commit_id) == 40


@pytest.mark.parametrize("scm_type", (SCM_TYPE_HG, SCM_TYPE_GIT))
@pytest.mark.django_db
def test_automation_job_merge_onto_fail(
    scm_type, repo_mc, treestatusdouble, get_automation_worker, monkeypatch
):
    repo = repo_mc(scm_type)

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="merge-onto",
        data={
            "action": "merge-onto",
            "commit_message": "bad merge",
            "strategy": None,
            "target": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        },
        order=0,
    )

    automation_worker = get_automation_worker(scm_type)
    automation_worker.worker_instance.applicable_repos.add(repo)

    assert not automation_worker.run_automation_job(
        job
    ), f"Job should fail for SCM: {scm_type}"
    assert job.status == JobStatus.FAILED
    assert "Aborting, could not perform `merge-onto`" in job.error


@pytest.mark.django_db
def test_automation_job_tag_success_git_tip_commit(
    repo_mc,
    treestatusdouble,
    get_automation_worker,
    request,
    monkeypatch,
    normal_patch,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={
            "action": "add-commit",
            "content": PATCH_GIT_1,
            "patch_format": "git-format-patch",
        },
        order=0,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="tag",
        data={"action": "tag", "name": tag_name, "target": None},
        order=1,
    )

    automation_worker = get_automation_worker(SCM_TYPE_GIT)
    automation_worker.worker_instance.applicable_repos.add(repo)

    assert automation_worker.run_automation_job(job)
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
def test_automation_job_tag_success_git_new_commit(
    repo_mc,
    treestatusdouble,
    get_automation_worker,
    request,
    monkeypatch,
    normal_patch,
):
    repo = repo_mc(SCM_TYPE_GIT)
    scm = repo.scm

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={
            "action": "add-commit",
            "content": PATCH_GIT_1,
            "patch_format": "git-format-patch",
        },
        order=0,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="tag",
        data={"action": "tag", "name": tag_name, "target": None},
        order=1,
    )

    automation_worker = get_automation_worker(SCM_TYPE_GIT)
    automation_worker.worker_instance.applicable_repos.add(repo)

    assert automation_worker.run_automation_job(job)
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
    get_automation_worker,
    request,
    monkeypatch,
    normal_patch,
):
    repo = repo_mc(SCM_TYPE_GIT)

    # Create a new commit that will be tagged
    _create_git_commit(request, Path(repo.system_path))

    tag_name = "v-tagtest-git"

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={
            "action": "add-commit",
            "content": PATCH_GIT_1,
            "patch_format": "git-format-patch",
        },
        order=0,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="tag",
        data={"action": "tag", "name": tag_name, "target": "bad-target"},
        order=1,
    )

    automation_worker = get_automation_worker(SCM_TYPE_GIT)
    automation_worker.worker_instance.applicable_repos.add(repo)

    assert not automation_worker.run_automation_job(job)
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED
    assert "Aborting, could not perform `tag`, action #1" in job.error


@pytest.mark.django_db
def test_automation_job_tag_success_hg(
    repo_mc,
    treestatusdouble,
    get_automation_worker,
    normal_patch,
    request,
):
    repo = repo_mc(SCM_TYPE_HG)

    repo_path = Path(repo.system_path)

    # Create a new commit that will be tagged.
    _create_hg_commit(request, repo_path)
    expected_commit = subprocess.run(
        ["hg", "log", "-r", ".", "-T", "{node}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    tag_name = "v-tagtest-hg"

    job = AutomationJob.objects.create(
        status=JobStatus.SUBMITTED,
        requester_email="test@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={
            "action": "add-commit",
            "content": normal_patch(1),
            "patch_format": "hgexport",
        },
        order=0,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="tag",
        data={"action": "tag", "name": tag_name, "target": None},
        order=1,
    )

    automation_worker = get_automation_worker(SCM_TYPE_HG)
    automation_worker.worker_instance.applicable_repos.add(repo)

    assert automation_worker.run_automation_job(job)
    assert job.status == JobStatus.LANDED, job.error

    # Verify the created commit is the one with the tag.
    expected_commit = subprocess.run(
        ["hg", "log", "-r", ".^", "-T", "{node}"],
        cwd=repo.system_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Verify tag was pushed to remote.
    tagged_commit = subprocess.run(
        ["hg", "log", "-r", f"tag('{tag_name}')", "-T", "{node}"],
        cwd=repo.system_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert expected_commit == tagged_commit


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
