import datetime
import json
import unittest.mock as mock

import pytest

from lando.api.legacy.workers.automation_worker import AutomationWorker
from lando.main.api import AutomationAction, AutomationJob
from lando.main.models import SCM_LEVEL_3, Repo
from lando.main.models.landing_job import LandingJobStatus
from lando.main.scm import SCM_TYPE_HG


@pytest.mark.django_db
def test_auth_missing_user_agent(client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "Authorization": "Bearer api-dummy-key",
        },
    )

    assert response.status_code == 401, "Missing `User-Agent` should result in 401."
    assert response.json() == {"details": "`User-Agent` header is required."}


@pytest.mark.django_db
def test_auth_missing_authorization_header(client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "User-Agent": "testuser@example.org",
        },
    )

    assert response.status_code == 401, "Missing `User-Agent` should result in 401."
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.django_db
def test_auth_unknown_user(client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "Authorization": "Bearer api-dummy-key",
            "User-Agent": "unknown-user@example.org",
        },
    )

    assert response.status_code == 401, "Unknown user should result in 401 status code."
    assert response.json() == {
        "details": "No user found for `User-Agent` unknown-user@example.org"
    }


@pytest.mark.django_db
def test_auth_invalid_token(client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "Authorization": "Bearer api-bad-key",
            "User-Agent": "testuser@example.org",
        },
    )

    assert (
        response.status_code == 401
    ), "Invalid API key shoudl result in 401 status code."
    assert response.json() == {"details": "API token is invalid."}


@pytest.mark.django_db
def test_automation_job_create_bad_repo(client, headless_user):
    body = {
        "actions": [
            {"action": "add-commit", "content": "TESTIN123"},
        ],
    }
    response = client.post(
        "/api/repo/blah/autoland",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "testuser@example.org",
            "Authorization": "Bearer api-dummy-key",
        },
    )

    assert response.status_code == 404, "Unknown repo should respond with 404."
    assert response.json() == {"details": "Repo blah does not exist."}


@pytest.mark.django_db
def test_automation_job_empty_actions(client, headless_user):
    body = {
        "actions": [],
    }
    response = client.post(
        "/api/repo/blah/autoland",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "testuser@example.org",
            "Authorization": "Bearer api-dummy-key",
        },
    )

    assert (
        response.status_code == 422
    ), "Empty `actions` should result in validation error."


@pytest.mark.parametrize(
    "bad_action,reason",
    (
        (
            {"action": "bad-action", "content": "TESTIN123"},
            "`bad-action` is an invalid action name.",
        ),
        (
            {"action": "add-commit", "content": {"test": 123}},
            "`content` should be a `str`.",
        ),
        (
            {"action": "add-commit", "content": 1},
            "`content` should be a `str`.",
        ),
    ),
)
@pytest.mark.django_db
def test_automation_job_create_bad_action(bad_action, reason, client, headless_user):
    body = {
        "actions": [bad_action],
    }
    response = client.post(
        "/api/repo/blah/autoland",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "testuser@example.org",
            "Authorization": "Bearer api-dummy-key",
        },
    )

    assert (
        response.status_code == 422
    ), f"Improper `actions` JSON schema should return 422 status: {reason}"


def is_isoformat_timestamp(date_string: str) -> bool:
    """Return `True` if `date_string` is an ISO format datetime string."""
    try:
        datetime.datetime.fromisoformat(date_string)
        return True
    except ValueError:
        return False


@pytest.mark.django_db
def test_automation_job_create(client, hg_server, hg_clone, headless_user):
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url=hg_server,
        required_permission=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
        system_path=hg_clone.strpath,
    )

    body = {
        "actions": [
            # Set `content` to a string integer to test order is preserved.
            {"action": "add-commit", "content": "0"},
            {"action": "add-commit", "content": "1"},
        ],
    }
    response = client.post(
        "/api/repo/mozilla-central/autoland",
        data=json.dumps(body),
        content_type="application/json",
        headers={
            "User-Agent": "testuser@example.org",
            "Authorization": "Bearer api-dummy-key",
        },
    )

    assert (
        response.status_code == 202
    ), "Successful submission should result in `202 Accepted` status code."

    response_json = response.json()
    assert isinstance(
        response_json["job_id"], int
    ), "Job ID should be returned as an `int`."
    assert response_json["status_url"] == "TODO"
    assert response_json["message"] == "Job is in the SUBMITTED state."
    assert is_isoformat_timestamp(
        response_json["created_at"]
    ), "Response should include an ISO formatted creation timestamp."

    job = AutomationJob.objects.get(id=response_json["job_id"])

    for index, action in enumerate(job.actions.all()):
        assert action.data["content"] == str(
            index
        ), "Actions should be retrieved in order of submission."


@pytest.mark.django_db
def test_get_job_status_not_found(client, headless_user):
    response = client.get(
        "/api/job/12345",
        headers={
            "User-Agent": "testuser@example.org",
            "Authorization": "Bearer api-dummy-key",
        },
    )
    assert (
        response.status_code == 404
    ), "API should respond with a 404 for non-existent job ID."


@pytest.mark.parametrize(
    "status,message",
    (
        (LandingJobStatus.SUBMITTED, "Job is in the SUBMITTED state."),
        (LandingJobStatus.IN_PROGRESS, "Job is in the IN_PROGRESS state."),
        (LandingJobStatus.DEFERRED, "Job is in the DEFERRED state."),
        (LandingJobStatus.FAILED, "Job is in the FAILED state."),
        (LandingJobStatus.LANDED, "Job is in the LANDED state."),
        (LandingJobStatus.CANCELLED, "Job is in the CANCELLED state."),
    ),
)
@pytest.mark.django_db
def test_get_job_status(status, message, client, headless_user):
    # Create a job and actions
    job = AutomationJob.objects.create(status=status)
    AutomationAction.objects.create(
        job_id=job, action_type="add-commit", data={"content": "test"}, order=0
    )

    # Fetch job status.
    response = client.get(
        f"/api/job/{job.id}",
        headers={
            "User-Agent": "testuser@example.org",
            "Authorization": "Bearer api-dummy-key",
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


PATCH_NORMAL_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()


@pytest.mark.django_db
def test_automation_job_add_commit(hg_server, hg_clone, monkeypatch):
    repo = Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url=hg_server,
        required_permission=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
        system_path=hg_clone.strpath,
    )
    scm = repo.scm

    # Create a job and actions
    job = AutomationJob.objects.create(
        status=LandingJobStatus.SUBMITTED,
        requester_email="example@example.com",
        target_repo=repo,
    )
    AutomationAction.objects.create(
        job_id=job,
        action_type="add-commit",
        data={"action": "add-commit", "content": PATCH_NORMAL_1},
        order=0,
    )

    worker = AutomationWorker(
        repos=Repo.objects.all(),
    )

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.automation_worker.AutomationWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    scm.push = mock.MagicMock()

    assert worker.run_automation_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == hg_server
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False}
