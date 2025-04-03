from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

from lando.main.models import Repo
from lando.main.models.revision import Revision
from lando.main.scm import (
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
)

DIFF_ONLY = """
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()


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


@pytest.mark.parametrize(
    "author, expected",
    [
        (
            "A. Uthor <author@moz.test>",
            ("A. Uthor", "author@moz.test"),
        ),
        (
            "author@moz.test",
            ("", "author@moz.test"),
        ),
        (
            "<author@moz.test>",
            ("", "author@moz.test"),
        ),
        (
            "A. Uthor",
            ("A. Uthor", ""),
        ),
        (
            "@ Uthor",
            ("@ Uthor", ""),
        ),
        (
            "<@ Uthor>",
            ("<@ Uthor>", ""),
        ),
    ],
)
def test__models__Revision___parse_author_string(author, expected):
    assert Revision._parse_author_string(author) == expected


@pytest.mark.django_db()
def test__models__Revision__metadata():
    author = "A. Uthor"
    email = "author@moz.test"
    commit_message = """Multiline Commit Message

    More lines
    """
    timestamp = datetime.now(tz=timezone.utc).strftime("%s")

    r = Revision.new_from_patch(
        raw_diff=DIFF_ONLY,
        patch_data={
            "author_name": author,
            "author_email": email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        },
    )

    assert r.author_name == author
    assert r.author_email == email
    assert r.author == f"{author} <{email}>"
    assert r.commit_message == commit_message
    assert r.timestamp == timestamp
    assert r.diff == DIFF_ONLY


@pytest.mark.parametrize(
    "branch,expected_branch", [(None, "main"), ("non-default", "non-default")]
)
def test_repo_default_branch_to_scm(branch: str, expected_branch: str):
    repo_path = "some_repo"
    repo = Repo(pull_path=repo_path, scm_type=SCM_TYPE_GIT, default_branch=branch)

    # repo.scm here is a GitSCM
    assert repo.scm.default_branch == expected_branch
