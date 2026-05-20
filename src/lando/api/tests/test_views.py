from unittest import mock

import pytest

from lando.main.models import Repo, SCMType


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
