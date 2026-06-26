from unittest import mock

import pytest
from django.test import Client

from lando.main.models import Repo, SCMType


@pytest.fixture
def repo_mc_github_api_client(repo_mc):
    repo_mc(SCMType.GIT, name="git-repo")

    mock_github_api_client = mock.MagicMock()
    mock_github_api_client.repo_is_private = False
    return mock_github_api_client


@pytest.fixture
def csrf_client(user, user_plaintext_password):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.login(username=user.username, password=user_plaintext_password)
    return csrf_client


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    for commit_map in commit_maps:
        response = client.get(f"/api/git2hg/git_repo/{commit_map.git_hash}")
        assert response.status_code == 200
        assert response.json() == commit_map.serialize()


@pytest.mark.django_db(transaction=True)
def test__views__hg2gitCommitMapView(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    for commit_map in commit_maps:
        response = client.get(f"/api/hg2git/git_repo/{commit_map.hg_hash}")
        assert response.status_code == 200
        assert response.json() == commit_map.serialize()


@pytest.mark.django_db(transaction=True)
def test__views__hg2gitCommitMapView_unknown_commit(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = client.get(f"/api/hg2git/git_repo/{'1' * 40}")
    assert response.status_code == 404
    assert response.json().get("error") == "No commits found"
    assert mock_catch_up.call_count == 1
    assert mock_catch_up.call_args[0] == ("git_repo",)


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_unknown_commit(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = client.get(f"/api/git2hg/git_repo/{'1' * 40}")
    assert response.status_code == 404
    assert response.json().get("error") == "No commits found"
    assert mock_catch_up.call_count == 1
    assert mock_catch_up.call_args[0] == ("git_repo",)


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_multiple_commits(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = client.get("/api/git2hg/git_repo/aaaaaaa")
    assert response.status_code == 400
    assert response.json().get("error") == "Multiple commits found"


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_short_hash(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    commit_map = commit_maps[2]
    response = client.get("/api/git2hg/git_repo/ccccccc")
    assert response.status_code == 200
    assert response.json() == commit_map.serialize()


@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend(
    phabdouble, client, user, user_phab_api_key, user_linked_to_phab, monkeypatch
):
    """Test that the Phabricator authentication backend behaves as expected."""
    test = client.get("/__version__")
    assert test.wsgi_request.user.is_anonymous

    # NOTE: due to limitations in phabdouble, the value of the token
    # is irrelevant here. This should be fixed in bug 2019413.
    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    test = client.get("/__version__", headers=headers)
    assert test.wsgi_request.user.is_authenticated


@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_unknown_phid(
    phabdouble, client, user, user_phab_api_key, monkeypatch
):
    """A valid token with no matching PHID or email should not authenticate."""
    # The phabdouble user has an email that does not match any local Django user,
    # so neither the PHID lookup nor the email fallback will find a profile.
    phabdouble.user(username="unknown_phab_user", email="unknown@example.com")

    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    test = client.get("/__version__", headers=headers)
    assert not test.wsgi_request.user.is_authenticated, (
        "A valid Phabricator token whose PHID and email do not match any local "
        "profile should not result in an authenticated request."
    )


@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_email_fallback(
    phabdouble, client, user, user_phab_api_key, monkeypatch
):
    """A valid token with no stored PHID should fall back to email and back-populate."""
    # The phabdouble user's email matches the local user, but the profile has no
    # `phabricator_phid` set. The backend should fall back to email lookup, authenticate
    # successfully, and store the PHID on the profile for future lookups.
    phab_user = phabdouble.user(username="phab_user", email=user.email)
    assert not user.profile.phabricator_phid, (
        "Profile should not have a PHID set before the email fallback test."
    )

    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    test = client.get("/__version__", headers=headers)
    assert test.wsgi_request.user.is_authenticated, (
        "Email fallback should authenticate the user when the PHID is not yet stored."
    )

    user.profile.refresh_from_db()
    assert user.profile.phabricator_phid == phab_user["phid"], (
        "The backend should back-populate the PHID on the profile after email fallback."
    )


@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_invalid_token(
    phabdouble, client, user, user_phab_api_key, user_linked_to_phab, monkeypatch
):
    """Test that the Phabricator authentication backend behaves as expected."""
    # NOTE: Currently, PhabricatorDouble does not have any awareness of the
    # Phabricator API token being used to authorize the client. Therefore,
    # any token passed here will result in a passing test, whether it is valid
    # or not. This should be fixed (see bug 2019413.)

    headers = {"X-Phabricator-API-Key": "INVALID_TOKEN"}
    test = client.get("/__version__", headers=headers)
    assert not test.wsgi_request.user.is_authenticated


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views__pull_request_api_view__private_repo(github_api_client, client):

    mock_github_api_client = mock.MagicMock()
    mock_pr = mock.MagicMock()

    mock_github_api_client.repo_is_private = True
    mock_github_api_client.build_pull_request.return_value = mock_pr

    github_api_client.return_value = mock_github_api_client

    repo = Repo.objects.create(
        name="git-repo-private",
        url="git.example.org/mozilla-conduit/test-repo-private",
        scm_type=SCMType.GIT,
    )

    test = client.get(f"/api/pulls/{repo.name}/1/landing_jobs")
    assert test.status_code == 404

    mock_github_api_client.repo_is_private = False
    test = client.get(f"/api/pulls/{repo.name}/1/landing_jobs")
    assert test.status_code == 200


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "payload, expected_status, expected_response",
    [
        (
            {
                "title": "Valid New Title",
                "body": "Valid New Body",
            },
            204,
            b"",
        ),
        (
            {
                "title": "",
                "body": "Valid New Body",
            },
            400,
            {
                "title": ["This field is required."],
            },
        ),
        (
            {
                "title": "a" * 300,
                "body": "Valid New Body",
            },
            400,
            {
                "title": ["Ensure this value has at most 256 characters (it has 300)."],
            },
        ),
    ],
)
def test__views__pull_request_content_api_view(
    github_api_client,
    authenticated_client,
    repo_mc_github_api_client,
    payload,
    expected_status,
    expected_response,
):
    """Test PullRequestContentAPIView validation and success responses."""

    github_api_client.return_value = repo_mc_github_api_client

    mock_pull_request = mock.MagicMock()

    repo_mc_github_api_client.build_pull_request.return_value = mock_pull_request
    repo_mc_github_api_client.update_pull_request_content.return_value = payload

    result = authenticated_client.put(
        "/api/pulls/git-repo/100",
        data=payload,
        content_type="application/json",
    )

    assert result.status_code == expected_status

    if expected_status == 204:
        assert result.content == expected_response
    else:
        response_json = result.json()
        for key, value in expected_response.items():
            assert response_json.get(key) == value


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views__pull_request_content_api_view__unauthenticated(
    github_api_client, client, repo_mc_github_api_client
):
    """An anonymous PUT should be rejected by the auth decorator."""

    github_api_client.return_value = repo_mc_github_api_client

    result = client.put(
        "/api/pulls/git-repo/100",
        data={"title": "Valid New Title", "body": "Valid New Body"},
        content_type="application/json",
    )

    # return 403 instead of 401 due to bug with django auth decorator. See: https://github.com/django/django/blob/main/django/core/handlers/exception.py#L75C51-L75C54
    assert result.status_code == 403
    assert b"403 Forbidden" in result.content


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views__pull_request_content_api_view__missing_csrf_token(
    github_api_client, csrf_client, repo_mc_github_api_client
):
    """An authenticated PUT without a CSRF token should be rejected."""
    github_api_client.return_value = repo_mc_github_api_client

    result = csrf_client.put(
        "/api/pulls/git-repo/100",
        data={"title": "Valid New Title", "body": "Valid New Body"},
        content_type="application/json",
    )
    assert result.status_code == 403
    assert b"403 Forbidden" in result.content


@mock.patch("lando.api.views.generate_warnings_and_blockers")
@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views_landing_job_pull_request_view__warnings(
    github_api_client, mock_warnings_and_blockers, authenticated_client, repo_mc
):
    repo = repo_mc(SCMType.GIT)
    mock_github_api_client = mock.MagicMock()
    github_api_client.return_value = mock_github_api_client
    mock_github_api_client.repo_is_private = False

    mock_pr = mock_github_api_client.build_pull_request.return_value
    mock_pr.author = ("Test Author", "test@email.com")
    mock_pr.commit_message = "Test Commit Message"
    mock_pr.number = 1
    mock_pr.head_sha = "aaa123"
    mock_pr.base_sha = "bbb123"
    mock_pr.patch = "diff --git a/abc b/def\n"
    mock_pr.reviews_summary = {}

    mock_warnings_and_blockers.return_value = {
        "warnings": ["warning-1", "warning-2"],
        "blockers": [],
    }

    old_warnings = authenticated_client.get(
        f"/api/pulls/{repo.name}/1/checks",
        content_type="application/json",
    ).json()["warnings"]

    response = authenticated_client.post(
        f"/api/pulls/{repo.name}/1/landing_jobs",
        data={
            "head_sha": "aaa123",
            "base_sha": "bbb123",
            "pull_number": 1,
            "old_warnings": old_warnings,
        },
        content_type="application/json",
    )

    new_warnings = response.json()["warnings"]

    assert new_warnings == old_warnings
    assert response.status_code == 201


@mock.patch("lando.api.views.generate_warnings_and_blockers")
@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views_landing_job_pull_request_view__warnings_mismatch(
    github_api_client, mock_warnings_and_blockers, authenticated_client, repo_mc
):

    mock_github_api_client = mock.MagicMock()
    github_api_client.return_value = mock_github_api_client
    mock_github_api_client.repo_is_private = False
    repo = repo_mc(SCMType.GIT)

    mock_pr = mock_github_api_client.build_pull_request.return_value
    mock_pr.author = ("Test Author", "test@email.com")
    mock_pr.commit_message = "Test Commit Message"
    mock_pr.number = 1
    mock_pr.head_sha = "aaa123"
    mock_pr.base_sha = "bbb123"
    mock_pr.patch = "diff --git a/abc b/def\n"
    mock_pr.reviews_summary = {}

    mock_warnings_and_blockers.return_value = {
        "warnings": ["warning-1", "warning-2"],
        "blockers": [],
    }

    old_warnings = authenticated_client.get(
        f"/api/pulls/{repo.name}/1/checks",
        content_type="application/json",
    ).json()["warnings"]

    mock_warnings_and_blockers.return_value = {
        "warnings": ["warning-2", "warning-3"],
        "blockers": [],
    }

    response = authenticated_client.post(
        f"/api/pulls/{repo.name}/1/landing_jobs",
        data={
            "head_sha": "aaa123",
            "base_sha": "bbb123",
            "pull_number": 1,
            "old_warnings": old_warnings,
        },
        content_type="application/json",
    )

    new_warnings = response.json()["warnings"]

    assert new_warnings == mock_warnings_and_blockers.return_value["warnings"]
    assert response.status_code == 400
    assert response.json()["errors"] == {"warnings": ["mismatch"]}
