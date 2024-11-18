import subprocess

import pytest

from lando.api.tests.conftest import git_setup_user
from lando.main.scm.git import GitScm


# We can't use fixtures directly in parametrize [0],
# so we jumps through some hoops.
# [0] https://github.com/pytest-dev/pytest/issues/349
@pytest.mark.parametrize(
    "path,repo_fixture_name,expected",
    (
        ("/non-existent-path", None, False),
        ("/tmp", None, False),
        (None, "git_repo", True),
    ),
)
def test_is_initialised(path, repo_fixture_name, expected, request):
    if not path:
        path = request.getfixturevalue(repo_fixture_name).strpath
    scm = GitScm(path)
    assert scm.repo_is_initialized == expected


def test_clone(tmpdir, git_repo):
    clone_path = tmpdir.mkdir("repo_test_clone")
    scm = GitScm(clone_path.strpath)
    scm.clone(git_repo.strpath)
    assert clone_path.exists(), "New git clone wasn't created"
    assert clone_path.join(
        ".git"
    ).exists(), "New git clone doesn't contain a .git directory"


@pytest.mark.parametrize(
    "strip_non_public_commits",
    (True, False),
)
def test_clean_repo(tmpdir, git_repo, strip_non_public_commits):
    clone_path = tmpdir.mkdir("repo_test_clean_repo")
    scm = GitScm(clone_path.strpath)
    scm.clone(git_repo.strpath)

    git_setup_user(clone_path.strpath)

    new_file = clone_path / "new_file"
    new_file.write_text("test", encoding="utf-8")

    assert 0 == subprocess.call(
        ["git", "add", new_file.basename], cwd=clone_path.strpath
    )
    assert 0 == subprocess.call(
        [
            "git",
            "commit",
            "-m",
            "adding new_file",
            "--author",
            "Lando <Lando@example.com>",
        ],
        cwd=clone_path.strpath,
    )

    new_untracked_file = clone_path / "new_untracked_file"
    new_untracked_file.write_text("test", encoding="utf-8")

    scm.clean_repo(strip_non_public_commits=strip_non_public_commits)

    assert (
        not new_untracked_file.check()
    ), f"{new_untracked_file.basename} still present after clean"
    if strip_non_public_commits:
        assert (
            not new_file.check()
        ), f"Locally commited {new_file.basename} still present after stripping clean"
    else:
        assert (
            new_file.check()
        ), f"Locally commited {new_file.basename} missing after non-stripping clean"
