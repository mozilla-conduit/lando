from unittest import mock

import pytest


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView(commit_maps, authenticated_client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = authenticated_client.get(f"/api/git2hg/test_git_repo/{'a' * 40}")
    assert response.status_code == 200
    assert response.json() == {"git_hash": "a" * 40, "hg_hash": "b" * 40}


@pytest.mark.django_db(transaction=True)
def test__views__hg2gitCommitMapView(commit_maps, authenticated_client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = authenticated_client.get(f"/api/hg2git/test_git_repo/{'b' * 40}")
    assert response.status_code == 200
    assert response.json() == {"git_hash": "a" * 40, "hg_hash": "b" * 40}


@pytest.mark.django_db(transaction=True)
def test__views__hg2gitCommitMapView_unknown_commit(
    commit_maps, authenticated_client, monkeypatch
):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = authenticated_client.get(f"/api/hg2git/test_git_repo/{'1' * 40}")
    assert response.status_code == 404
    assert response.json() == {"error": "No commits found"}
    assert mock_catch_up.call_count == 1
    assert mock_catch_up.call_args[0] == ("test_git_repo",)


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_unknown_commit(
    commit_maps, authenticated_client, monkeypatch
):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = authenticated_client.get(f"/api/git2hg/test_git_repo/{'1' * 40}")
    assert response.status_code == 404
    assert response.json() == {"error": "No commits found"}
    assert mock_catch_up.call_count == 1
    assert mock_catch_up.call_args[0] == ("test_git_repo",)
