import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from lando.main.scm.git import GitSCM


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
def test_GitSCM_is_initialised(path, repo_fixture_name, expected, request):
    if not path:
        path = request.getfixturevalue(repo_fixture_name)
    scm = GitSCM(str(path))
    assert scm.repo_is_initialized == expected


def test_GitSCM_clone(tmp_path: Path, git_repo: Path):
    clone_path = tmp_path / "repo_test_GitSCM_clone"
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))
    assert clone_path.exists(), "New git clone wasn't created"
    assert (
        clone_path / ".git"
    ).exists(), "New git clone doesn't contain a .git directory"


@pytest.mark.parametrize(
    "strip_non_public_commits",
    (True, False),
)
def test_GitSCM_clean_repo(
    tmp_path: Path,
    git_repo: Path,
    git_setup_user: Callable,
    strip_non_public_commits: bool,
):
    clone_path = tmp_path / "repo_test_GitSCM_clean_repo"
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    new_file = clone_path / "new_file"
    new_file.write_text("test", encoding="utf-8")

    assert 0 == subprocess.call(["git", "add", new_file.name], cwd=str(clone_path))
    assert 0 == subprocess.call(
        [
            "git",
            "commit",
            "-m",
            "adding new_file",
            "--author",
            "Lando <Lando@example.com>",
        ],
        cwd=str(clone_path),
    )

    new_untracked_file = clone_path / "new_untracked_file"
    new_untracked_file.write_text("test", encoding="utf-8")

    scm.clean_repo(strip_non_public_commits=strip_non_public_commits)

    assert (
        not new_untracked_file.exists()
    ), f"{new_untracked_file.name} still present after clean"
    if strip_non_public_commits:
        assert (
            not new_file.exists()
        ), f"Locally commited {new_file.name} still present after stripping clean"
    else:
        assert (
            new_file.exists()
        ), f"Locally commited {new_file.name} missing after non-stripping clean"
