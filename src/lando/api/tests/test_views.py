from unittest import mock

import pytest


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
    phabdouble, client, user, user_phab_api_key, monkeypatch
):
    """Test that the Phabricator authentication backend behaves as expected."""
    phabdouble.user(username="phab_user", email=user.email)
    test = client.get("/__version__")
    assert test.wsgi_request.user.is_anonymous

    # NOTE: due to limitations in phabdouble, the value of the token
    # is irrelevant here. This should be fixed in bug 2019413.
    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    test = client.get("/__version__", headers=headers)
    assert test.wsgi_request.user.is_authenticated


@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_invalid_token(
    phabdouble, client, user, user_phab_api_key, monkeypatch
):
    """Test that the Phabricator authentication backend behaves as expected."""
    # NOTE: Currently, PhabricatorDouble does not have any awareness of the
    # Phabricator API token being used to authorize the client. Therefore,
    # any token passed here will result in a passing test, whether it is valid
    # or not. This should be fixed (see bug 2019413.)

    phabdouble.user(username="phab_user", email=user.email)
    headers = {"X-Phabricator-API-Key": "INVALID_TOKEN"}
    test = client.get("/__version__", headers=headers)
    assert not test.wsgi_request.user.is_authenticated
