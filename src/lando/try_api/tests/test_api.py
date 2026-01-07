import base64
import json
from typing import Callable
from unittest.mock import Mock, patch

import pytest
from django.test.client import Client

from lando.main.models.commit_map import CommitMap
from lando.main.models.jobs import JobStatus
from lando.main.models.landing_job import LandingJob
from lando.main.models.repo import Repo


@pytest.mark.django_db()
@patch("lando.try_api.api.AccessTokenAuth.authenticate")
def test_legacy_try_patches_invalid_user(
    mock_authenticate: Mock,
    client: Client,
):
    mock_authenticate.return_value = None

    response = client.post(
        "/try/patches",
        # This payload doesn't matter, as we only check authentication.
        data="{}",
        content_type="application/json",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return None, as a failure to
        # authenticate the user.
        headers={"AuThOrIzAtIoN": "bEaReR token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 401
    ), "Invalid user to legacy Try API should result in 401"


@pytest.mark.django_db()
@patch("lando.try_api.api.AccessTokenAuth.authenticate")
def test_legacy_try_patches_auth_redirect(
    mock_authenticate: Mock,
    client: Client,
):
    response = client.post(
        "/try/patches",
        # This payload doesn't matter, as we only check the redirection.
        data="{}",
        content_type="application/json",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which is just a non-failing mock.
        headers={"AuThOrIzAtIoN": "bEaReR token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 308
    ), "Valid token to legacy Try API should result in 308"


@pytest.mark.django_db()
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
def test_try_api_patches_invalid_user(
    mock_authenticate: Mock,
    client: Client,
):
    mock_authenticate.return_value = None

    response = client.post(
        "/try/patches",
        # This payload doesn't matter, as we only check authentication.
        data="{}",
        content_type="application/json",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return None, as a failure to
        # authenticate the user.
        headers={"AuThOrIzAtIoN": "bEaReR token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 401, "Invalid token to Try API should result in 401"


@pytest.mark.django_db()
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
def test_try_api_patches_no_scm1(
    mock_authenticate: Mock,
    scm_user: Callable,
    to_profile_permissions: Callable,
    client: Client,
):
    user = scm_user(to_profile_permissions([]), "password")
    mock_authenticate.return_value = user

    response = client.post(
        "/api/try/patches",
        # This payload doesn't matter, as we only check authentication.
        data="{}",
        content_type="application/json",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return None, as a failure to
        # authenticate the user.
        headers={"AuThOrIzAtIoN": "bEaReR token no_scm1"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"

    assert (
        response.status_code == 403
    ), "Missing permissions to legacy Try API should result in 403"


@pytest.mark.django_db()
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
def test_try_api_patches_not_try(
    mock_authenticate: Mock,
    mocked_repo_config: Mock,
    scm_user: Callable,
    to_profile_permissions: Callable,
    client: Client,
):
    user = scm_user(to_profile_permissions(["scm_level_1"]), "password")
    mock_authenticate.return_value = user

    request_payload = {
        "repo": "mozilla-central",  # from the mocked_repo_config
        "base_commit": "0" * 40,
        "base_commit_vcs": "git",
        "patches": [
            "YmFzZTY0Cg==",  # "base64"
            "YmFzZTY0LXRvbwo=",  # "base64-too"
        ],
        "patch_format": "git-format-patch",
    }

    response = client.post(
        "/api/try/patches",
        data=json.dumps(request_payload),
        content_type="application/json",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return a User.
        headers={"AuThOrIzAtIoN": "bEaReR token not_try"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 400
    ), "Request to Try API for non-try report should result in 400"


@pytest.mark.django_db()
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
def test_try_api_patches_success(
    mock_authenticate: Mock,
    mocked_repo_config: Mock,
    scm_user: Callable,
    to_profile_permissions: Callable,
    commit_maps: list[CommitMap],
    git_patch: Callable,
    client: Client,
):
    user = scm_user(to_profile_permissions(["scm_level_1"]), "password")
    mock_authenticate.return_value = user

    for map in commit_maps:
        # This is hardcoded for now.
        map.git_repo_name = "firefox"
        map.save()

    request_payload = {
        # "repo": "some",  # defaults to try, from the mocked_repo_config
        "base_commit": commit_maps[0].git_hash,
        "base_commit_vcs": "git",
        "patches": [
            base64.b64encode(git_patch(0).encode()).decode(),
            base64.b64encode(git_patch(1).encode()).decode(),
        ],
        "patch_format": "git-format-patch",
    }

    response = client.post(
        "/api/try/patches",
        data=json.dumps(request_payload),
        content_type="application/json",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return a User.
        headers={"AuThOrIzAtIoN": "bEaReR token success"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 201
    ), f"Valid request to Try API should result in 201: {response.text}"

    rj = response.json()
    assert "id" in rj, "Missing job id in success response"

    job = LandingJob.objects.get(id=rj["id"])

    assert job, "Try LandingJob should have been created"
    assert job.status == JobStatus.SUBMITTED, "Try LandingJob not in the expected state"
    assert job.target_repo == Repo.objects.get(
        name="try"
    ), "Try LandingJob not against the Try repo"
    assert (
        job.requester_email == user.email
    ), "Try LandingJob request email not as expected"
    assert (
        len(job.revisions) == 2
    ), "Unexpected number of revisions associated to Try LandingJob"
    assert (
        job.target_commit_hash == commit_maps[0].hg_hash
    ), "Target commit hash not correctly converted"
