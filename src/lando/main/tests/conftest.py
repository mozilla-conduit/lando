import pathlib
import subprocess
import time
from pathlib import Path

import pytest
import requests
from django.contrib.auth.models import User

from lando.main.models import Profile


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
    subprocess.run(["git", "branch", "-m", "main"], check=True, cwd=repo_dir)
    file = repo_dir / "first"
    file.write_text("first file!")
    _git_setup_user(repo_dir)
    subprocess.run(["git", "add", file.name], check=True, cwd=repo_dir)
    subprocess.run(["git", "commit", "-m", "first commit"], check=True, cwd=repo_dir)
    return repo_dir


@pytest.fixture
def git_setup_user():
    return _git_setup_user


def _git_setup_user(repo_dir):
    """Configure the git user locally to repo_dir so as not to mess with the real user's configuration."""
    subprocess.run(["git", "config", "user.name", "Py Test"], check=True, cwd=repo_dir)
    subprocess.run(
        ["git", "config", "user.email", "pytest@lando.example.net"],
        check=True,
        cwd=repo_dir,
    )


@pytest.fixture
def hg_clone(hg_server, tmpdir):
    clone_dir = tmpdir.join("hg_clone")
    subprocess.run(["hg", "clone", hg_server, clone_dir.strpath], check=True)
    return clone_dir


@pytest.fixture
def hg_test_bundle(request):
    return Path(request.path.parent.parent.parent).joinpath(
        "api", "tests", "data", "test-repo.bundle"
    )


@pytest.fixture
def hg_server(hg_test_bundle, tmpdir):
    # TODO: Select open port.
    port = "8000"
    hg_url = "http://localhost:" + port

    repo_dir = tmpdir.mkdir("hg_server")
    subprocess.run(["hg", "clone", hg_test_bundle, repo_dir], check=True, cwd="/")

    serve = subprocess.Popen(
        [
            "hg",
            "serve",
            "--config",
            "web.push_ssl=False",
            "--config",
            "web.allow_push=*",
            "-p",
            port,
            "-R",
            repo_dir,
        ]
    )
    if serve.poll() is not None:
        raise Exception("Failed to start the mercurial server.")
    # Wait until the server is running.
    for _i in range(10):
        try:
            requests.get(hg_url)
        except Exception:
            time.sleep(1)
        break

    yield hg_url
    serve.kill()


@pytest.fixture
def conduit_permissions():
    permissions = (
        "scm_level_1",
        "scm_level_2",
        "scm_level_3",
        "scm_conduit",
    )
    all_perms = Profile.get_all_scm_permissions()

    return [all_perms[p] for p in permissions]


@pytest.fixture
def user_plaintext_password():
    return "test_password"


@pytest.fixture
def user(user_plaintext_password, conduit_permissions):
    user = User.objects.create_user(
        username="test_user",
        password=user_plaintext_password,
        email="testuser@example.org",
    )

    user.profile = Profile(user=user, userinfo={"name": "test user"})

    for permission in conduit_permissions:
        user.user_permissions.add(permission)

    user.save()
    user.profile.save()

    return user


@pytest.fixture
def headless_user(user):
    user.profile.save_lando_api_key("api-dummy-key")
    return user
