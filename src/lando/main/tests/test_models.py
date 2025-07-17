from datetime import datetime, timezone
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

from lando.main.models import CommitMap, Repo
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
    "scm_type, url, expected_url, expected_normalized_url,",
    [
        (
            SCM_TYPE_GIT,
            "https://github.com/mozilla-conduit/test-repo.git/",
            "https://github.com/mozilla-conduit/test-repo.git",
            "https://github.com/mozilla-conduit/test-repo",
        ),
        (
            SCM_TYPE_GIT,
            "https://github.com/mozilla-conduit/test-repo.git",
            "https://github.com/mozilla-conduit/test-repo.git",
            "https://github.com/mozilla-conduit/test-repo",
        ),
        (
            SCM_TYPE_GIT,
            "https://github.com/mozilla-conduit/test-repo",
            "https://github.com/mozilla-conduit/test-repo.git",
            "https://github.com/mozilla-conduit/test-repo",
        ),
        (
            SCM_TYPE_HG,
            "https://hg.mozilla.org/conduit-testing/test-repo/",
            "https://hg.mozilla.org/conduit-testing/test-repo",
            "https://hg.mozilla.org/conduit-testing/test-repo",
        ),
        (
            SCM_TYPE_HG,
            "https://hg.mozilla.org/conduit-testing/test-repo",
            "https://hg.mozilla.org/conduit-testing/test-repo",
            "https://hg.mozilla.org/conduit-testing/test-repo",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
def test__models__Repo__normalized_url(
    scm_type, url, expected_url, expected_normalized_url, monkeypatch
):
    mock__find_supporting_scm = mock.MagicMock()
    mock__find_supporting_scm.return_value = scm_type
    monkeypatch.setattr(Repo, "_find_supporting_scm", mock__find_supporting_scm)
    repo = Repo(url=url)
    repo.save()

    assert repo.url == expected_url
    assert repo.normalized_url == expected_normalized_url


@pytest.mark.parametrize(
    "scm_type, url, expected_git_repo_name,",
    [
        (
            SCM_TYPE_GIT,
            "https://github.com/mozilla-conduit/test-repo.git/",
            "test-repo",
        ),
        (
            SCM_TYPE_GIT,
            "https://github.com/mozilla-firefox/firefox.git/",
            "firefox",
        ),
        (
            SCM_TYPE_HG,
            "https://hg.mozilla.org/conduit-testing/test-repo/",
            None,
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
def test__models__Repo__git_repo_name(
    scm_type, url, expected_git_repo_name, monkeypatch
):
    mock__find_supporting_scm = mock.MagicMock()
    mock__find_supporting_scm.return_value = scm_type
    monkeypatch.setattr(Repo, "_find_supporting_scm", mock__find_supporting_scm)
    repo = Repo(url=url)
    repo.save()

    if not expected_git_repo_name:
        with pytest.raises(ValueError):
            assert repo.git_repo_name == expected_git_repo_name
    else:
        assert repo.git_repo_name == expected_git_repo_name


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


@pytest.mark.django_db(transaction=True)
def test__models__CommitMap___find_last_node(commit_maps):
    assert commit_maps[-1] == CommitMap._find_last_node("git_repo")


@pytest.mark.django_db(transaction=True)
def test__models__CommitMap__find_last_hg_node(commit_maps, monkeypatch):
    mock__find_last_node = mock.MagicMock()
    monkeypatch.setattr(CommitMap, "_find_last_node", mock__find_last_node)
    last_hg_node = CommitMap.find_last_hg_node("git_repo")
    assert mock__find_last_node.call_count == 1
    assert mock__find_last_node.call_args[0] == ("git_repo",)
    assert last_hg_node == mock__find_last_node("git_repo").hg_hash


@pytest.mark.django_db(transaction=True)
def test__models__CommitMap__catch_up(commit_maps, monkeypatch):
    mock_find_last_hg_node = MagicMock()
    mock_fetch_push_data = MagicMock()
    monkeypatch.setattr(CommitMap, "find_last_hg_node", mock_find_last_hg_node)
    monkeypatch.setattr(CommitMap, "fetch_push_data", mock_fetch_push_data)

    CommitMap.catch_up("git_repo")
    assert mock_find_last_hg_node.call_count == 1
    assert mock_fetch_push_data.call_count == 1
    assert mock_find_last_hg_node.call_args[0] == ("git_repo",)
    assert mock_fetch_push_data.call_args[1] == {
        "git_repo_name": "git_repo",
        "fromchangeset": mock_find_last_hg_node("git_repo"),
    }


@pytest.mark.django_db(transaction=True)
def test__models__CommitMap__fetch_push_data(commit_maps, monkeypatch):
    last_hg_node = commit_maps[-1].hg_hash
    previous_commit_map_count = CommitMap.objects.all().count()
    mock_requests_get = MagicMock()
    mock_requests_get(
        "https://hg.mozilla.org/git_repo/json-pushes",
        params={"fromchangeset": last_hg_node},
    ).json.return_value = {
        "some_push": {"changesets": ["1" * 40], "git_changesets": ["2" * 40]}
    }
    monkeypatch.setattr("lando.main.models.commit_map.requests.get", mock_requests_get)
    CommitMap.fetch_push_data("git_repo", fromchangeset=last_hg_node)
    assert CommitMap.objects.all().count() == previous_commit_map_count + 1
    assert CommitMap.find_last_hg_node("git_repo") == "1" * 40


@pytest.mark.django_db(transaction=True)
def test__models__CommitMap__fetch_push_data_invalid_response(commit_maps, monkeypatch):
    last_hg_node = commit_maps[-1].hg_hash
    previous_commit_map_count = CommitMap.objects.all().count()
    mock_requests_get = MagicMock()
    mock_requests_get(
        "https://hg.mozilla.org/git_repo/json-pushes",
        params={"fromchangeset": last_hg_node},
    ).json.return_value = {
        "some_push": {"changesets": ["1" * 40, "2" * 40], "git_changesets": ["3" * 40]}
    }
    monkeypatch.setattr("lando.main.models.commit_map.requests.get", mock_requests_get)
    with pytest.raises(ValueError) as e:
        CommitMap.fetch_push_data("git_repo", fromchangeset=last_hg_node)
    assert e.value.args == (
        "Number of hg changesets does not match number of git changesets: 2 vs 1",
    )
    assert CommitMap.objects.all().count() == previous_commit_map_count
