from unittest.mock import patch

import pytest

from lando.main.models import Repo


@pytest.mark.parametrize(
    "git_returncode,hg_returncode,scm",
    ((255, 0, Repo.HG), (0, 255, Repo.GIT)),
)
@patch("lando.main.models.repo.subprocess")
def test__models__Repo__scm(subprocess, git_returncode, hg_returncode, scm, db):
    repo_path = "some_repo"

    def call(*args, **kwargs):
        if args[0] == ["git", "ls-remote", repo_path]:
            return git_returncode
        elif args[0] == ["hg", "identify", repo_path]:
            return hg_returncode

    subprocess.call.side_effect = call

    repo = Repo(pull_path=repo_path)
    repo.save()

    assert repo.scm == scm

    if scm == Repo.GIT:
        assert repo.is_git_repo
        assert repo.is_hg_repo is False

    if scm == Repo.HG:
        assert repo.is_hg_repo
        assert repo.is_git_repo is False


@pytest.mark.parametrize("scm,call_count", ((Repo.HG, 0), (Repo.GIT, 0)))
@patch("lando.main.models.repo.subprocess")
def test__models__Repo__scm_not_calculated_when_preset(subprocess, scm, call_count, db):
    repo_path = "some_hg_repo"
    repo = Repo(pull_path=repo_path, scm=scm)
    repo.save()
    assert subprocess.call.call_count == call_count
