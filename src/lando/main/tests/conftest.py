import pathlib
import subprocess

import pytest


@pytest.fixture
def git_repo(tmp_path: pathlib.Path):
    """
    Creates a temporary Git repository for testing purposes.

    Args:
        tmp_path (pathlib.Path): The base temporary directory path (pytest fixture)

    Returns:
        pathlib.Path: The path to the created Git repository.
    """
    repo_dir = tmp_path / "git_repo"
    subprocess.run(["git", "init", repo_dir], check=True)
    file = repo_dir / "first"
    file.write_text("first file!")
    git_setup_user(repo_dir)
    subprocess.run(["git", "add", file.name], check=True, cwd=repo_dir)
    subprocess.run(["git", "commit", "-m", "first commit"], check=True, cwd=repo_dir)
    return repo_dir


def git_setup_user(repo_dir):
    """Configure the git user locally to repo_dir so as not to mess with the real user's configuration."""
    subprocess.run(["git", "config", "user.name", "Py Test"], check=True, cwd=repo_dir)
    subprocess.run(
        ["git", "config", "user.email", "pytest@lando.example.net"],
        check=True,
        cwd=repo_dir,
    )
