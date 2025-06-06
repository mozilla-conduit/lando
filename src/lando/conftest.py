import pathlib
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import py
import pytest
import requests
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType

from lando.api.legacy.stacks import (
    RevisionStack,
    build_stack_graph,
    request_extended_revision_data,
)
from lando.api.legacy.transplants import build_stack_assessment_state
from lando.api.tests.mocks import TreeStatusDouble
from lando.headless_api.models.automation_job import AutomationJob
from lando.headless_api.models.tokens import ApiToken
from lando.main.models import (
    SCM_LEVEL_1,
    SCM_LEVEL_3,
    Profile,
    Repo,
    Worker,
)
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.scm.commit import CommitData
from lando.pushlog.models import Commit, File, Push, Tag

# The name of the Phabricator project used to tag revisions requiring data classification.
NEEDS_DATA_CLASSIFICATION_SLUG = "needs-data-classification"

PATCH_NORMAL_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
Bug 35: add another line
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
No bug: add one more line
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
Bug 42: add another file
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

PATCH_GIT_1 = """\
From be6df88a1c2c64621ab9dfdf244272748e93c26f Mon Sep 17 00:00:00 2001
From: Py Test <pytest@lando.example.net>
Date: Tue, 22 Apr 2025 02:02:55 +0000
Subject: No bug: add another line

---
 test.txt | 1 +
 1 file changed, 1 insertion(+)

diff --git a/test.txt b/test.txt
index 2a02d41..45e9938 100644
--- a/test.txt
+++ b/test.txt
@@ -1 +1,2 @@
 TEST
+adding another line
-- 
"""  # noqa: W291, `git` adds a trailing whitespace after `--`.


@pytest.fixture
def normal_patch():
    """Return a factory providing one of several Hg-formatted patches."""
    _patches = [
        PATCH_NORMAL_1,
        PATCH_NORMAL_2,
        PATCH_NORMAL_3,
    ]

    def _patch(number=0):
        return _patches[number]

    return _patch


@pytest.fixture
def git_patch():
    """Return a factory providing one of several git patches.

    Currently, there's only one patch.
    """
    _patches = [
        PATCH_GIT_1,
    ]

    def _patch(number=0):
        return _patches[number]

    return _patch


@pytest.fixture
def git_repo_seed() -> Path:
    """
    Return the path to a patch to set up a base git repo for tests.

    The diff can  apply on an empty repo to create a known base for application
    of other patches as part of the tests.
    """
    return settings.BASE_DIR / "main" / "tests" / "data"


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
def git_setup_user():
    return _git_setup_user


def _git_setup_user(repo_dir: Path):
    """Configure the git user locally to repo_dir so as not to mess with the real user's configuration."""
    _run_commands(
        [
            ["git", "config", "user.name", "Py Test"],
            ["git", "config", "user.email", "pytest@lando.example.net"],
        ],
        repo_dir,
    )


def _run_commands(commands: list[list[str]], cwd: Path):
    for c in commands:
        subprocess.run(c, check=True, cwd=cwd)


@pytest.fixture
def git_repo(
    tmp_path: Path, git_repo_seed: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """
    Creates a temporary Git repository for testing purposes.

    Args:
        tmp_path (pathlib.Path): The base temporary directory path (pytest fixture)

    Returns:
        pathlib.Path: The path to the created Git repository.
    """
    # Force the committer date to a known value. This allows to have
    # predictable commit SHAs when applying known patches on top.
    epoch = "1970-01-01T00:00:00"
    monkeypatch.setenv("GIT_COMMITTER_DATE", epoch)

    repo_dir = tmp_path / "git_repo"
    subprocess.run(["git", "init", repo_dir], check=True)
    subprocess.run(["git", "branch", "-m", "main"], check=True, cwd=repo_dir)
    _git_setup_user(repo_dir)
    _git_ignore_denyCurrentBranch(repo_dir)
    for patch in sorted(git_repo_seed.glob("*")):
        subprocess.run(
            ["git", "am", "--committer-date-is-author-date", str(patch)],
            check=True,
            cwd=repo_dir,
        )

    # Create a separate base branch for branch tests.
    _run_commands(
        [
            ["git", "checkout", "-b", "dev"],
            ["git", "commit", "--date", epoch, "--allow-empty", "-m", "dev"],
            ["git", "checkout", "main"],
        ],
        repo_dir,
    )
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
def headless_permission():
    content_type = ContentType.objects.get_for_model(AutomationJob)
    return Permission.objects.get(
        codename="add_automationjob", content_type=content_type
    )


@pytest.fixture
def headless_user(user, headless_permission):
    user.user_permissions.add(headless_permission)
    user.save()
    user.profile.save()

    token = ApiToken.create_token(user)
    return user, token


@pytest.fixture
def needs_data_classification_project(phabdouble):
    return phabdouble.project(NEEDS_DATA_CLASSIFICATION_SLUG)


@pytest.fixture
def create_state(
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    """Create a `StackAssessmentState`."""

    def create_state_handler(revision, landing_assessment=None):
        phab = phabdouble.get_phabricator_client()
        supported_repos = Repo.get_mapping()
        nodes, edges = build_stack_graph(revision)
        stack_data = request_extended_revision_data(phab, list(nodes))
        stack = RevisionStack(set(stack_data.revisions.keys()), edges)
        relman_group_phid = release_management_project["phid"]
        data_policy_review_phid = needs_data_classification_project["phid"]

        return build_stack_assessment_state(
            phab,
            supported_repos,
            stack_data,
            stack,
            relman_group_phid,
            data_policy_review_phid,
            landing_assessment=landing_assessment,
        )

    return create_state_handler


@pytest.fixture
def treestatus_url():
    """A string holding the Tree Status base URL."""
    return settings.TREESTATUS_URL


@pytest.fixture
def treestatusdouble(monkeypatch, treestatus_url):
    """Mock the Tree Status service and build fake responses."""
    yield TreeStatusDouble(monkeypatch, treestatus_url)


#
# PushLog fixtures
#
@pytest.fixture
def make_repo():
    def repo_factory(seqno: int) -> Repo:
        """Create a non-descript repository with a sequence number in the test DB."""
        return Repo.objects.create(
            name=f"repo-{seqno}",
            scm_type=SCM_TYPE_GIT,
            url=f"https://repo-{seqno}",
            default_branch=f"main-{seqno}",
        )

    return repo_factory


@pytest.fixture
def make_hash():
    def hash_factory(seqno: int):
        """Create a hash-like hex string, including the seqno in decimal representation."""
        return str(seqno).zfill(8) + "f" + 31 * "0"

    return hash_factory


@pytest.fixture
def make_commit(make_hash):
    def commit_factory(repo: Repo, seqno: int, message=None) -> Commit:
        """Create a non-descript commit with a sequence number in the test DB."""
        if not message:
            message = f"Commit {seqno}"

        return Commit.objects.create(
            hash=make_hash(seqno),
            repo=repo,
            author=f"author-{seqno}",
            desc=message,
            datetime=datetime.now(tz=timezone.utc),
        )

    return commit_factory


@pytest.fixture
def make_file():
    def file_factory(repo: Repo, seqno: int) -> File:
        """Create a non-descript file with a sequence number in the test DB."""
        return File.objects.create(
            repo=repo,
            name=f"file-{seqno}",
        )

    return file_factory


@pytest.fixture
def make_tag():
    def tag_factory(repo: Repo, seqno: int, commit: Commit) -> Tag:
        """Create a non-descript tag with a sequence number in the test DB."""
        return Tag.objects.create(
            repo=repo,
            name=f"tag-{seqno}",
            commit=commit,
        )

    return tag_factory


@pytest.fixture
def make_push():
    def push_factory(
        repo: Repo, commits: list[Commit] | None = None, tags: list[Tag] | None = None
    ):
        """Create a non-descript push containing the associated commits in the test DB."""
        push = Push.objects.create(repo=repo, user="Push-User")
        for c in commits or []:
            push.commits.add(c)
        for t in tags or []:
            push.tags.add(t)
        push.save()

        return push

    return push_factory


@pytest.fixture
def make_scm_commit(make_hash):
    def scm_commit_factory(seqno: int):
        return CommitData(
            hash=make_hash(seqno),
            author=f"author-{seqno}",
            desc=f"""SCM Commit {seqno}

Another line""",
            datetime=datetime.now(tz=timezone.utc),
            # The first commit doesn't have a parent.
            parents=[make_hash(seqno - 1)] if seqno > 1 else [],
            files=[f"/file-{s}" for s in range(seqno)],
        )

    return scm_commit_factory


@pytest.fixture
def assert_same_commit_data():
    def assertion(commit: Commit, scm_commit: CommitData):
        assert commit.hash == scm_commit.hash

        assert len(commit.parents) == len(scm_commit.parents)
        assert set(commit.parents) == set(scm_commit.parents)

        assert commit.author == scm_commit.author
        assert commit.datetime == scm_commit.datetime
        assert commit.desc == scm_commit.desc

        assert len(commit.files) == len(scm_commit.files)
        assert set(commit.files) == set(scm_commit.files)

    return assertion
