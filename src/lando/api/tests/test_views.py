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
