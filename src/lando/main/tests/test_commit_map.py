from typing import Callable
from unittest import mock

import pytest

from lando.main.models import CommitMap
from lando.main.scm import SCMType


@pytest.mark.django_db(transaction=True)
def test_CommitMap_git2hg(commit_maps):
    for cmap in commit_maps:
        assert CommitMap.git2hg(cmap.git_repo_name, cmap.git_hash) == cmap.hg_hash


@pytest.mark.django_db(transaction=True)
def test_CommitMap_git2hg_catchup(monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.main.models.CommitMap.catch_up", mock_catch_up)

    with pytest.raises(CommitMap.DoesNotExist):
        CommitMap.git2hg("git_test_repo", "z" * 40)

    assert mock_catch_up.assert_called, (
        "CommitMap.catch_up wasn't called for a missing Git commit"
    )


@pytest.mark.django_db(transaction=True)
def test_CommitMap_hg2git(commit_maps):
    for cmap in commit_maps:
        assert CommitMap.hg2git(cmap.git_repo_name, cmap.hg_hash) == cmap.git_hash


@pytest.mark.django_db(transaction=True)
def test_CommitMap_hg2git_catchup(monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.main.models.CommitMap.catch_up", mock_catch_up)

    with pytest.raises(CommitMap.DoesNotExist):
        CommitMap.hg2git("git_test_repo", "z" * 40)

    assert mock_catch_up.assert_called, (
        "CommitMap.catch_up wasn't called for a missing Hg commit"
    )


@pytest.mark.django_db
def test_CommitMap_get_hg_repo_name_hardcoded(repo_mc: Callable):
    repo_map = CommitMap.REPO_MAPPING[0]
    # Create a Repo with a name matching the map,
    # to test the fallback to the hardcoded mapping.
    repo_mc(SCMType.GIT, name=repo_map[0])

    assert CommitMap.get_hg_repo_name(repo_map[0]) == repo_map[1]


@pytest.mark.django_db
def test_CommitMap_get_hg_repo_name_in_repo(repo_mc: Callable):
    repo_map = CommitMap.REPO_MAPPING[0]
    # Create a Repo with a name matching the second map entry,
    # and override the mapping to use the first entry
    repo_name = CommitMap.REPO_MAPPING[1][0]
    repo_mc(SCMType.GIT, name=repo_name, commit_map_name=repo_map[0])

    assert CommitMap.get_hg_repo_name(repo_name) == repo_map[1]


@pytest.mark.django_db(transaction=True)
def test_CommitMap_git2hg_multiple(commit_maps):
    with pytest.raises(CommitMap.MultipleObjectsReturned):
        assert CommitMap.git2hg(commit_maps[0].git_repo_name, "aaaaa")
