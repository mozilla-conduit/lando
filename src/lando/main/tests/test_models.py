from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

from lando.main.models import Repo
from lando.main.scm import (
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
)


@pytest.mark.parametrize(
    "git_returncode,hg_returncode,scm_type",
    ((255, 0, SCM_TYPE_HG), (0, 255, SCM_TYPE_GIT)),
)
@patch("lando.main.scm.GitSCM")
@patch("lando.main.scm.HgSCM")
@pytest.mark.django_db(transaction=True)
def test__models__Repo__scm(
    HgSCM,
    GitSCM,
    monkeypatch,
    git_returncode,
    hg_returncode,
    scm_type,
):
    repo_path = "some_repo"

    HgSCM.repo_is_supported = MagicMock(name="repo_is_supported")
    HgSCM.repo_is_supported.return_value = not hg_returncode

    GitSCM.repo_is_supported = MagicMock(name="repo_is_supported")
    GitSCM.repo_is_supported.return_value = not git_returncode

    monkeypatch.setattr(
        "lando.main.models.repo.SCM_IMPLEMENTATIONS",
        {
            SCM_TYPE_GIT: GitSCM,
            SCM_TYPE_HG: HgSCM,
        },
    )

    repo = Repo(pull_path=repo_path)
    repo.save()

    assert repo.scm_type == scm_type


@pytest.mark.parametrize("scm_type,call_count", ((SCM_TYPE_HG, 0), (SCM_TYPE_GIT, 0)))
@patch("lando.main.scm.git.subprocess")
@patch("lando.main.scm.hg.subprocess")
@pytest.mark.django_db(transaction=True)
def test__models__Repo__scm_not_calculated_when_preset(
    hg_subprocess, git_subprocess, scm_type, call_count
):
    subprocess_map = {SCM_TYPE_GIT: git_subprocess, SCM_TYPE_HG: hg_subprocess}
    subprocess = subprocess_map[scm_type]
    repo_path = "some_hg_repo"
    repo = Repo(pull_path=repo_path, scm_type=scm_type)
    repo.save()
    assert subprocess.call.call_count == 0


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
