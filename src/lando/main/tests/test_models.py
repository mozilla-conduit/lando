from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

from lando.main.models import Repo
from lando.main.scm import (
    SCM_GIT,
    SCM_HG,
)


@pytest.mark.parametrize(
    "git_returncode,hg_returncode,scm",
    ((255, 0, SCM_HG), (0, 255, SCM_GIT)),
)
@patch("lando.main.models.repo.HgSCM")
@patch("lando.main.models.repo.subprocess")
def test__models__Repo__scm(
    subprocess,
    HgSCM,
    monkeypatch,
    git_returncode,
    hg_returncode,
    scm,
    db,
):
    repo_path = "some_repo"

    def call(*args, **kwargs):
        if args[0] == ["git", "ls-remote", repo_path]:
            return git_returncode

    subprocess.call.side_effect = call

    HgSCM.repo_is_supported = MagicMock(name="repo_is_supported")
    HgSCM.repo_is_supported.return_value = not hg_returncode

    repo = Repo(pull_path=repo_path)

    # Skip the GitSCM stub implementation
    monkeypatch.setattr("lando.main.models.repo.SCM_IMPLEMENTATIONS", {SCM_HG: HgSCM})

    repo.save()

    assert repo.scm == scm


@pytest.mark.parametrize("scm,call_count", ((SCM_HG, 0), (SCM_GIT, 0)))
@patch("lando.main.models.repo.subprocess")
def test__models__Repo__scm_not_calculated_when_preset(subprocess, scm, call_count, db):
    repo_path = "some_hg_repo"
    repo = Repo(pull_path=repo_path, scm=scm)
    repo.save()
    assert subprocess.call.call_count == call_count


@pytest.mark.parametrize(
    "path, expected_exception",
    [
        (settings.REPO_ROOT + "/valid_path", None),
        (settings.REPO_ROOT + "invalid_path", ValidationError),
        (settings.REPO_ROOT + "/invalid/path", ValidationError),
        ("/invalid_path", ValidationError),
    ],
)
def test__models__Repo__system_path_validator(path, expected_exception):
    repo = Repo(
        name="name",
        url="http://example.com",
        required_permission="required_permission",
        system_path=path,
    )
    if expected_exception:
        with pytest.raises(expected_exception):
            repo.clean_fields()
    else:
        repo.clean_fields()  # Should not raise any exception
