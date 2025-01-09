import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo_seed(request) -> Path:
    return Path(__file__).parent / "data" / "test-repo.patch"


@pytest.fixture
def git_repo(tmp_path: Path, git_repo_seed: Path) -> Path:
    """
    Creates a temporary Git repository for testing purposes.

    Args:
        tmp_path (pathlib.Path): The base temporary directory path (pytest fixture)

    Returns:
        pathlib.Path: The path to the created Git repository.
    """
    repo_dir = tmp_path / "git_repo"
    subprocess.run(["git", "init", repo_dir], check=True)
    subprocess.run(["git", "branch", "-m", "main"], check=True, cwd=repo_dir)
    _git_setup_user(repo_dir)
    _git_ignore_denyCurrentBranch(repo_dir)
    subprocess.run(["git", "am", str(git_repo_seed)], check=True, cwd=repo_dir)
    subprocess.run(["git", "show"], check=True, cwd=repo_dir)
    subprocess.run(["git", "branch"], check=True, cwd=repo_dir)
    return repo_dir


@pytest.fixture
def git_setup_user():
    return _git_setup_user


def _git_setup_user(repo_dir: Path):
    """Configure the git user locally to repo_dir so as not to mess with the real user's configuration."""
    subprocess.run(["git", "config", "user.name", "Py Test"], check=True, cwd=repo_dir)
    subprocess.run(
        ["git", "config", "user.email", "pytest@lando.example.net"],
        check=True,
        cwd=repo_dir,
    )


def _git_ignore_denyCurrentBranch(repo_dir: Path):
    """Disable error when pushing to this non-bare repo.

    This is a sane protection in general, but it gets in the way of the tests here,
    where we just want a target, and don't care much about the final state of this
    target after everything is done."""
    subprocess.run(
        ["git", "config", "receive.denyCurrentBranch", "ignore"],
        check=True,
        cwd=repo_dir,
    )
