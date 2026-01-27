import base64
import json
from typing import Callable
from unittest.mock import MagicMock, Mock

import pytest
from django.contrib.auth.models import Permission, User
from django.core.handlers.wsgi import WSGIRequest
from django.test.client import Client

from lando.main.models.commit_map import CommitMap
from lando.main.models.jobs import JobStatus
from lando.main.models.landing_job import LandingJob
from lando.main.models.repo import Repo


@pytest.fixture
def client_post(
    client: Client, commit_maps: list[CommitMap], git_patch: Callable
) -> Callable:
    """Fixture for making POST requests with the test client."""

    def _post(
        path: str,
        data: str | None = None,
        content_type: str = "application/json",
        headers: dict | None = None,
    ):
        if not data:
            data = json.dumps(
                {
                    # "repo": "some",  # defaults to try, from the mocked_repo_config_try
                    "base_commit": commit_maps[0].git_hash,
                    "base_commit_vcs": "git",
                    "patches": [
                        base64.b64encode(git_patch(0).encode()).decode(),
                    ],
                    "patch_format": "git-format-patch",
                }
            )

        if headers is None:
            headers = {"AuThOrIzAtIoN": "bEaReR token"}
        return client.post(path, data=data, content_type=content_type, headers=headers)

    return _post


@pytest.fixture
def mock_authenticate_builder(monkeypatch: pytest.MonkeyPatch) -> Callable:
    """Allows to build a Mock authentication system which returns a specified User."""

    def builder(user: User) -> Mock:
        mock = MagicMock()

        def authenticate_callback(request: WSGIRequest, token: str) -> User:
            request.user = user
            return user

        mock.side_effect = authenticate_callback

        monkeypatch.setattr("lando.utils.ninja_auth.AccessTokenAuth.authenticate", mock)
        return mock

    return builder


@pytest.mark.django_db()
def test_legacy_try_patches_invalid_user(
    mock_authenticate_builder: Callable,
    client_post: Callable,
):
    mock_authenticate = mock_authenticate_builder(None)

    response = client_post("/try/patches")

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 401
    ), "Invalid user to legacy Try API should result in 401"


@pytest.mark.django_db()
def test_legacy_try_patches_auth_redirect(
    mock_authenticate_builder: Callable,
    scm_user: Callable,
    client_post: Callable,
):
    user = scm_user(
        [Permission.objects.get(codename="scm_level_1")],
        "password",
    )
    mock_authenticate = mock_authenticate_builder(user)

    response = client_post("/try/patches")

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 308
    ), "Valid token to legacy Try API should result in 308"


@pytest.mark.django_db()
def test_try_api_patches_invalid_user(
    mock_authenticate_builder: Callable,
    client_post: Callable,
):
    mock_authenticate = mock_authenticate_builder(None)

    response = client_post("/try/patches")

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 401, "Invalid token to Try API should result in 401"


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "group_scm_1,superuser",
    (
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ),
)
def test_try_api_patches_no_scm1(
    mock_authenticate_builder: Callable,
    mocked_repo_config_try: Mock,
    scm_user: Callable,
    client_post: Callable,
    make_superuser: Callable,
    group_scm_1: bool,
    superuser: bool,
):
    if group_scm_1:
        user = scm_user(
            [],
            "password",
            [Permission.objects.get(codename="scm_level_1")],
        )
    else:
        user = scm_user([], "password")

    if superuser:
        user = make_superuser(user)

    mock_authenticate = mock_authenticate_builder(user)

    response = client_post(
        "/api/try/patches",
        headers={"AuThOrIzAtIoN": "bEaReR token no_scm1"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"

    assert (
        response.status_code == 403
    ), "Missing permissions to Try API should result in 403"

    rj = response.json()
    assert rj, "Error response should be a parseable (RFC 7807) JSON payload"
    assert "title" in rj, f"Missing title in error 400 response: {response.text}"
    assert rj["title"] == "Forbidden"
    assert "detail" in rj, f"Missing detail in error 400 response: {response.text}"
    assert rj["detail"] == "Missing permissions: main.scm_level_1"


@pytest.mark.django_db()
def test_try_api_patches_not_try(
    mock_authenticate_builder: Callable,
    mocked_repo_config_try: Mock,
    scm_user: Callable,
    client_post: Callable,
):
    user = scm_user([Permission.objects.get(codename="scm_level_1")], "password")
    mock_authenticate = mock_authenticate_builder(user)

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

    response = client_post(
        "/api/try/patches",
        data=json.dumps(request_payload),
        headers={"AuThOrIzAtIoN": "bEaReR token not_try"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 400
    ), "Request to Try API for non-try report should result in 400"


@pytest.mark.django_db()
@pytest.mark.parametrize("invalid_base64", (False, True))
def test_try_api_patches_invalid_data(
    mock_authenticate_builder: Callable,
    mocked_repo_config_try: Mock,
    scm_user: Callable,
    commit_maps: list[CommitMap],
    git_patch: Callable,
    client_post: Callable,
    invalid_base64: bool,
):
    user = scm_user([Permission.objects.get(codename="scm_level_1")], "password")
    mock_authenticate = mock_authenticate_builder(user)

    for map in commit_maps:
        # This is hardcoded for now.
        map.git_repo_name = "firefox"
        map.save()

    bad_patch = base64.b64encode("bad patch".encode()).decode()
    if invalid_base64:
        bad_patch = "notbase64butlookslikeit"

    request_payload = {
        # "repo": "some",  # defaults to try, from the mocked_repo_config
        "base_commit": commit_maps[0].git_hash,
        "base_commit_vcs": "git",
        "patches": [base64.b64encode(git_patch(0).encode()).decode(), bad_patch],
        "patch_format": "git-format-patch",
    }

    response = client_post(
        "/api/try/patches",
        data=json.dumps(request_payload),
        headers={"AuThOrIzAtIoN": "bEaReR token success"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert (
        response.status_code == 400
    ), f"Valid request to Try API with incorrect patch data should result in 400: {response.text}"

    rj = response.json()
    assert "title" in rj, f"Missing title in error 400 response: {response.text}"
    assert "detail" in rj, f"Missing detail in error 400 response: {response.text}"
    if invalid_base64:
        assert rj["title"] == "Invalid base64 patch data"
        assert rj["detail"].startswith("Invalid base64 data for patch 1")
    else:
        assert rj["title"] == "Invalid patch data"
        assert rj["detail"].startswith("Invalid patch data for patch 1")


@pytest.mark.django_db()
def test_try_api_patches_success(
    mock_authenticate_builder: Callable,
    mocked_repo_config_try: Mock,
    scm_user: Callable,
    commit_maps: list[CommitMap],
    git_patch: Callable,
    client_post: Callable,
):
    user = scm_user([Permission.objects.get(codename="scm_level_1")], "password")

    mock_authenticate = mock_authenticate_builder(user)

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

    response = client_post(
        "/api/try/patches",
        data=json.dumps(request_payload),
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
