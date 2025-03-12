import pathlib
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import py
import pytest
import requests
from django.conf import settings
from django.contrib.auth.models import User

from lando.headless_api.models.tokens import ApiToken
from lando.main.models import (
    SCM_LEVEL_1,
    SCM_LEVEL_3,
    Profile,
    Repo,
    Worker,
)
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG

PATCH_NORMAL_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()

PATCH_NORMAL_2 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,2 +1,3 @@
 TEST
 adding another line
+adding one more line
""".lstrip()

PATCH_NORMAL_3 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
deleted file mode 100644
--- a/test.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-TEST
diff --git a/blah.txt b/blah.txt
new file mode 100644
--- /dev/null
+++ b/blah.txt
@@ -0,0 +1,1 @@
+TEST
""".lstrip()


@pytest.fixture
def normal_patch():
    """Return one of several "normal" patches."""
    _patches = [
        PATCH_NORMAL_1,
        PATCH_NORMAL_2,
        PATCH_NORMAL_3,
    ]

    def _patch(number=0):
        return _patches[number]

    return _patch


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
    target after everything is done.
    """
    subprocess.run(
        ["git", "config", "receive.denyCurrentBranch", "ignore"],
        check=True,
        cwd=repo_dir,
    )


@pytest.fixture
def git_repo_seed() -> Path:
    """
    Return the path to a patch to set up a base git repo for tests.

    The diff can  apply on an empty repo to create a known base for application
    of other patches as part of the tests.
    """
    return Path(__file__).parent / "main" / "tests" / "data" / "test-repo.patch"


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

    # Create a separate base branch for branch tests.
    subprocess.run(["git", "checkout", "-b", "dev"], check=True, cwd=repo_dir)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "dev"], check=True, cwd=repo_dir
    )

    subprocess.run(["git", "checkout", "main"], check=True, cwd=repo_dir)
    return repo_dir


@pytest.mark.django_db
def hg_repo_mc(
    hg_server: str,
    hg_clone: py.path,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    force_push: bool = False,
    push_target: str = "",
    automation_enabled: bool = True,
) -> Repo:
    params = {
        "required_permission": SCM_LEVEL_3,
        "url": hg_server,
        "push_path": hg_server,
        "pull_path": hg_server,
        "system_path": hg_clone.strpath,
        # The option below can be overriden in the parameters
        "approval_required": approval_required,
        "autoformat_enabled": autoformat_enabled,
        "force_push": force_push,
        "push_target": push_target,
        "automation_enabled": automation_enabled,
    }
    repo = Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central-hg",
        **params,
    )
    repo.save()
    return repo


@pytest.mark.django_db
def git_repo_mc(
    git_repo: pathlib.Path,
    tmp_path: pathlib.Path,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    force_push: bool = False,
    push_target: str = "",
    automation_enabled: bool = True,
) -> Repo:
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    params = {
        "required_permission": SCM_LEVEL_3,
        "url": str(git_repo),
        "push_path": str(git_repo),
        "pull_path": str(git_repo),
        "system_path": repos_dir / "git_repo",
        # The option below can be overriden in the parameters
        "approval_required": approval_required,
        "autoformat_enabled": autoformat_enabled,
        "force_push": force_push,
        "push_target": push_target,
        "automation_enabled": automation_enabled,
    }

    repo = Repo.objects.create(
        scm_type=SCM_TYPE_GIT,
        name="mozilla-central-git",
        **params,
    )
    repo.save()
    repo.scm.prepare_repo(repo.pull_path)
    return repo


@pytest.fixture()
def repo_mc(
    # Git
    git_repo: pathlib.Path,
    tmp_path: pathlib.Path,
    # Hg
    hg_server: str,
    hg_clone: py.path,
) -> Callable:
    def factory(
        scm_type: str,
        *,
        approval_required: bool = False,
        autoformat_enabled: bool = False,
        force_push: bool = False,
        push_target: str = "",
        automation_enabled: bool = True,
    ) -> Repo:
        params = {
            "approval_required": approval_required,
            "autoformat_enabled": autoformat_enabled,
            "force_push": force_push,
            "push_target": push_target,
            "automation_enabled": automation_enabled,
        }

        if scm_type == SCM_TYPE_GIT:
            return git_repo_mc(git_repo, tmp_path, **params)
        elif scm_type == SCM_TYPE_HG:
            return hg_repo_mc(hg_server, hg_clone, **params)
        raise Exception(f"Unknown SCM Type {scm_type=}")

    return factory


@pytest.fixture
def mock_repo_config(monkeypatch):
    def set_repo_config(config):
        monkeypatch.setattr("lando.api.legacy.repos.REPO_CONFIG", config)

    return set_repo_config


@pytest.fixture
def mocked_repo_config(mock_repo_config):
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url="http://hg.test",
        required_permission=SCM_LEVEL_3,
        approval_required=False,
    )
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-uplift",
        url="http://hg.test/uplift",
        required_permission=SCM_LEVEL_3,
        approval_required=True,
    )
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-new",
        url="http://hg.test/new",
        required_permission=SCM_LEVEL_3,
        commit_flags=[("VALIDFLAG1", "testing"), ("VALIDFLAG2", "testing")],
    )
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="try",
        url="http://hg.test/try",
        push_path="http://hg.test/try",
        pull_path="http://hg.test",
        required_permission=SCM_LEVEL_1,
        short_name="try",
        is_phabricator_repo=False,
        force_push=True,
    )
    # Copied from legacy "local-dev". Should have been in mocked repos.
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="uplift-target",
        url="http://hg.test",  # TODO: fix this? URL is probably incorrect.
        required_permission=SCM_LEVEL_1,
        approval_required=True,
        milestone_tracking_flag_template="cf_status_firefox{milestone}",
    )


@pytest.fixture
def hg_clone(hg_server, tmpdir):
    clone_dir = tmpdir.join("hg_clone")
    subprocess.run(["hg", "clone", hg_server, clone_dir.strpath], check=True)
    return clone_dir


@pytest.fixture
def hg_test_bundle():
    return settings.BASE_DIR / "api" / "tests" / "data" / "test-repo.bundle"


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
def landing_worker_instance(mocked_repo_config):
    def _instance(scm, **kwargs):
        worker = Worker.objects.create(sleep_seconds=0.1, scm=scm, **kwargs)
        worker.applicable_repos.set(Repo.objects.filter(scm_type=scm))
        return worker

    return _instance


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
    token = ApiToken.create_token(user)
    return user, token
