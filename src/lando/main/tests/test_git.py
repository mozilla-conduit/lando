import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lando.main.scm.git import GitSCM


@pytest.mark.parametrize(
    "path,expected",
    (
        ("/non-existent-path", False),
        ("/tmp", False),
        (None, True),  # generate a default path
    ),
)
def test_GitSCM_is_initialised(git_repo: Path, path: str, expected: bool):
    if not path:
        path = str(git_repo)
    scm = GitSCM(path)
    assert scm.repo_is_initialized == expected


def test_GitSCM_clone(git_repo: Path, tmp_path: Path, monkeypatch):
    clone_path = tmp_path / "repo_test_GitSCM_clone"
    scm = GitSCM(str(clone_path))

    mock_git_run = _monkeypatch_scm(monkeypatch, scm, "_git_run")

    scm.clone(str(git_repo))

    mock_git_run.assert_called_with("clone", str(git_repo), str(clone_path), cwd="/")
    assert clone_path.exists(), f"New git clone {clone_path} wasn't created"
    assert (
        clone_path / ".git"
    ).exists(), f"New git clone {clone_path} doesn't contain a .git directory"


@pytest.mark.parametrize(
    "strip_non_public_commits",
    (True, False),
)
def test_GitSCM_clean_repo(
    git_repo: Path,
    tmp_path: Path,
    git_setup_user: Callable,
    strip_non_public_commits: bool,
    monkeypatch,
):
    clone_path = tmp_path / "repo_test_GitSCM_clean_repo"
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    new_file = clone_path / "new_file"
    new_file.write_text("test", encoding="utf-8")

    # Those two command should not raise exceptions
    subprocess.run(["git", "add", new_file.name], cwd=str(clone_path), check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "adding new_file",
            "--author",
            "Lando <Lando@example.com>",
        ],
        cwd=str(clone_path),
        check=True,
    )

    new_untracked_file = clone_path / "new_untracked_file"
    new_untracked_file.write_text("test", encoding="utf-8")

    mock_git_run = _monkeypatch_scm(monkeypatch, scm, "_git_run")

    scm.clean_repo(strip_non_public_commits=strip_non_public_commits)

    mock_git_run.assert_called_with("clean", "-fdx", cwd=str(clone_path))
    if strip_non_public_commits:
        mock_git_run.assert_any_call(
            "reset", "--hard", f"origin/{scm.default_branch}", cwd=str(clone_path)
        )

    assert (
        strip_non_public_commits != new_file.exists()
    ), f"strip_non_public_commits not honoured for {new_file}"


def _monkeypatch_scm(monkeypatch, scm: GitSCM, method: str) -> MagicMock:
    """
    Mock a method on `scm` to test the call, but let it continue with its original side
    effect, so we can test that it's correct, too.

    Returns:
    MagicMock: The mock object.
    """
    original = scm.__getattribute__(method)
    mock = MagicMock()
    mock.side_effect = original
    monkeypatch.setattr(scm, method, mock)
    return mock
