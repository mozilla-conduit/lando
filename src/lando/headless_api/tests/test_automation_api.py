import datetime
import json
import secrets
import unittest.mock as mock

import pytest
from django.contrib.auth.hashers import check_password

from lando.api.legacy.workers.automation_worker import AutomationWorker
from lando.headless_api.api import AutomationAction, AutomationJob
from lando.headless_api.models.tokens import ApiToken
from lando.main.models import SCM_LEVEL_3, Repo
from lando.main.models.landing_job import LandingJobStatus
from lando.main.scm import SCM_TYPE_HG


@pytest.mark.django_db
def test_auth_missing_user_agent(client, headless_user):
    user, token = headless_user

    # Create a job and actions
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
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
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
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
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
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
    job = AutomationJob.objects.create(status=LandingJobStatus.SUBMITTED)
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
            {"action": "add-commit", "content": "TESTIN123"},
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
            {"action": "add-commit", "content": "0"},
            {"action": "add-commit", "content": "1"},
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
        response.status_code == 403
    ), "Automation disabled for repo should `403 Forbidden` status."
    assert (
        response.json()["details"]
        == "Repo mozilla-central is not enabled for automation."
    ), "Details should indicate automation API is disabled for repo."


@pytest.mark.django_db
def test_automation_job_create_user_automation_disabled(
    client, headless_user, hg_server, hg_clone
):
    user, token = headless_user

    # Disable automation enabled for user.
    user.profile.is_automation_user = False
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
            {"action": "add-commit", "content": "0"},
            {"action": "add-commit", "content": "1"},
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
def test_automation_job_create(client, hg_server, hg_clone, headless_user):
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
            {"action": "add-commit", "content": "0"},
            {"action": "add-commit", "content": "1"},
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
        name="automation-worker",
        scm=SCM_TYPE_HG,
    )
    return AutomationWorker(worker)


@pytest.mark.django_db
def test_automation_job_add_commit_success(
    hg_server, hg_clone, hg_automation_worker, repo_mc, monkeypatch, normal_patch
):
    repo = repo_mc(SCM_TYPE_HG)
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
        data={"action": "add-commit", "content": normal_patch(1)},
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
    assert scm.push.call_args[1] == {"push_target": "", "force_push": False}
    assert job.status == LandingJobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40, "Landed commit ID should be a 40-char SHA."


@pytest.mark.django_db
def test_automation_job_add_commit_fail(
    hg_server, hg_clone, repo_mc, hg_automation_worker, monkeypatch
):
    repo = repo_mc(SCM_TYPE_HG)
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
        data={"action": "add-commit", "content": "FAIL"},
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
    assert job.status == LandingJobStatus.FAILED, "Automation job should fail."
    assert scm.push.call_count == 0


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
        ApiToken.verify_token(token) == user
    ), "verify_token should return the user for a valid token."


@pytest.mark.django_db
def test_invalid_token_prefix_invalid(headless_user):
    user, token = headless_user

    # Modify the token prefix so it is invalid.
    invalid_token = "f" + token[1:]

    # verify_token should raise a `ValueError` for bad token.
    with pytest.raises(ValueError):
        ApiToken.verify_token(invalid_token)


@pytest.mark.django_db
def test_invalid_token_prefix_valid(headless_user):
    user, token = headless_user

    # Modify the end of the token to confirm a found prefix must still
    # match the hash/salt.
    invalid_token = token[:-1] + "f"

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
        ApiToken.verify_token(token1) == user
    ), "First token with common prefix should return headless user."
    assert (
        ApiToken.verify_token(token2) == user
    ), "Second token with common prefix should return headless user."
