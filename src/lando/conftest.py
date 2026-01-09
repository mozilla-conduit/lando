import json
import os
import pathlib
import re
import subprocess
import time
import unittest.mock as mock
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from ninja import NinjaAPI
from ninja.testing import TestClient
from requests.models import HTTPError

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
    CommitMap,
    Profile,
    Repo,
    Worker,
)
from lando.main.models.landing_job import LandingJob, add_job_with_revisions
from lando.main.models.revision import Revision
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.scm.commit import CommitData
from lando.main.scm.git import GitSCM
from lando.main.scm.hg import HgSCM
from lando.pushlog.models import Commit, File, Push, Tag
from lando.treestatus.models import Tree, TreeStatus

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
From dd187015cd85d59c2a65a3a18c67b2b05e7739b9 Mon Sep 17 00:00:00 2001
From: Py Test <pytest@lando.example.net>
Date: Tue, 22 Apr 2025 02:02:55 +0000
Subject: No bug: add another file and line

---
 test.txt  | 1 +
 test2.txt | 1 +
 2 files changed, 2 insertions(+)
 create mode 100644 test2.txt

diff --git a/test.txt b/test.txt
index 2a02d41..45e9938 100644
--- a/test.txt
+++ b/test.txt
@@ -1 +1,2 @@
 TEST
+adding another line
diff --git a/test2.txt b/test2.txt
new file mode 100644
index 0000000..7898192
--- /dev/null
+++ b/test2.txt
@@ -0,0 +1 @@
+a
-- 
"""  # noqa: W291, `git` adds a trailing whitespace after `--`.

PATCH_GIT_2 = """\
From ed0231509340a9664aaa06f53a5a1685d2f15b7c Mon Sep 17 00:00:00 2001
From: Lando <lando@lando.test>
Date: Wed, 26 Nov 2025 06:28:19 +0000
Subject: No bug: adding a line in context

---
 test.txt | 1 +
 1 file changed, 1 insertion(+)

diff --git a/test.txt b/test.txt
index 2a02d41..0ff72ad 100644
--- a/test.txt
+++ b/test.txt
@@ -1 +1,2 @@
+new line inserted
 TEST
-- 
"""  # noqa: W291, `git` adds a trailing whitespace after `--`.


PATCH_GIT_BINARY_1 = """\
From be6df88a1c2c64621ab9dfdf244272748e93c26f Mon Sep 17 00:00:00 2001
From: Py Test <pytest@lando.example.net>
Date: Tue, 22 Apr 2025 02:02:55 +0000
Subject: almost-not-binary: add testcase for Bug 1984942

Differential Revision: http://phabricator.test/D71
---
 .gitattributes    |   1 +
 almost-not-binary | Bin 0 -> 28 bytes
 2 files changed, 1 insertion(+)
 create mode 100644 .gitattributes
 create mode 100644 almost-not-binary

diff --git a/almost-not-binary b/almost-not-binary
new file mode 100644
index 0000000000000000000000000000000000000000..226cdd7b100a1d9e624b8040b5a60cadd93716f1
GIT binary patch
literal 28
jc${NkT%4t)XONnktCyUg%cZ54m{OKmoL{6@Ud#mmcC-k;

literal 0
Hc$@<O00001



diff --git a/.gitattributes b/.gitattributes
new file mode 100644
--- /dev/null
+++ b/.gitattributes
@@ -0,0 +1 @@
+almost-not-binary diff

""".lstrip()

PATCH_GIT_DOS_LINE_ENDING = """
From daf43dabd1cc2d4f386519d61eee6e7abb766108 Mon Sep 17 00:00:00 2001
From: Py Test <pytest@lando.example.net>
Date: Wed, 26 Nov 2025 04:05:36 +0000
Subject: [PATCH] No bug: add a DOS file

---
 test-dos.txt | 2 ++
 1 file changed, 2 insertions(+)
 create mode 100644 test-dos.txt

diff --git a/test-dos.txt b/test-dos.txt
new file mode 100644
index 0000000..f04873a
--- /dev/null
+++ b/test-dos.txt
@@ -0,0 +1,2 @@
+one DOS-terminated line in the file\r
+one DOS-terminated line\r
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
def create_patch_revision(normal_patch: Callable):
    """A fixture that fake uploads a patch"""

    normal_patch_0 = normal_patch(0)

    def _create_patch_revision(number: int, patch: str = normal_patch_0):
        """Create revision number `number`, with patch text `patch`.

        `patch` will default to the first normal patch fixture if unspecified. However,
        if explicitly set to None, the `normal_patch` fixture will be used to get
        normal patch number `number-1`."""
        if not patch:
            patch = normal_patch(number - 1)
        revision = Revision()
        revision.revision_id = number
        revision.diff_id = number
        revision.patch = patch
        revision.save()
        return revision

    return _create_patch_revision


@pytest.fixture
def git_patch():
    """Return a factory providing one of several git patches.

    * The first two patches are normal patches.
    * The third one contains binary weirdness.
    * The third has DOS line terminators (\r\n).
    """
    _patches = [
        PATCH_GIT_1,
        PATCH_GIT_2,
        PATCH_GIT_BINARY_1,
        PATCH_GIT_DOS_LINE_ENDING,
    ]

    def _patch(number: int = 0):
        return _patches[number]

    return _patch


@pytest.fixture
def create_pull_request_revision(git_patch: Callable):
    """A fixture that fake uploads a patch"""

    git_patch_0 = git_patch(0)

    def _create_pull_request_revision(number: int, patches: str = git_patch_0):
        """Create revision number `number`, with patch text `patch`.

        `patch` will default to the first git patch fixture if unspecified. However,
        if explicitly set to None, the `git_patch` fixture will be used to get
        normal patch number `number-1`."""
        if not patches:
            patches = git_patch(number - 1)
        revision = Revision()
        revision.pull_number = number
        # XXX: We use static metadata for now. In the future, we may want to extract dynamic
        # metadata from the `patches` passed to the fixture.
        revision.patch_data = {
            "author_name": "create_pull_request_revision",
            "author_email": "create_pull_request_revision@pytest",
            "commit_message": f"No bug - commit message for PR {number}",
            "timestamp": f"{1764132923 + number}",
        }
        # We set the _patches_ as the concatenation of all requested patches, as can be
        # obtained from Pull Requests.
        revision.patches = patches
        revision.save()
        return revision

    return _create_pull_request_revision


PATCH_DIFF = """
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()

PATCH_DIFF_2 = """
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,2 +1,3 @@
 TEST
 adding another line
+adding one more line
""".lstrip()

PATCH_SYMLINK_DIFF = """
diff --git a/blahfile_real b/blahfile_real
new file mode 100644
index 0000000..907b308
--- /dev/null
+++ b/blahfile_real
@@ -0,0 +1 @@
+blah
diff --git a/blahfile_symlink b/blahfile_symlink
new file mode 120000
index 0000000..55faaf5
--- /dev/null
+++ b/blahfile_symlink
@@ -0,0 +1 @@
+/home/sheehan/blahfile
""".lstrip()

PATCH_TRY_TASK_CONFIG_DIFF = """
index 0000000..663cbc2
--- /dev/null
+++ b/blah.json
@@ -0,0 +1 @@
+{"123":"456"}
diff --git a/try_task_config.json b/try_task_config.json
new file mode 100644
index 0000000..e44d36d
--- /dev/null
+++ b/try_task_config.json
@@ -0,0 +1 @@
+{"env": {"TRY_SELECTOR": "fuzzy"}, "version": 1, "tasks": ["source-test-cram-tryselect"]}
""".lstrip()

PATCH_NSS_DIFF = """
diff --git a/security/nss/.keep b/security/nss/.keep
new file mode 100644
index 0000000..e69de29
""".lstrip()

PATCH_NSPR_DIFF = """
diff --git a/nsprpub/.keep b/nsprpub/.keep
new file mode 100644
index 0000000..e69de29
""".lstrip()

PATCH_SUBMODULE_DIFF = """
diff --git a/.gitmodules b/.gitmodules
new file mode 100644
index 0000000..4c39732
--- /dev/null
+++ b/.gitmodules
@@ -0,0 +1,3 @@
+[submodule "submodule"]
+       path = submodule
+       url = https://github.com/mozilla-conduit/test-repo
"""

FAILING_CHECK_TYPES = [
    "nobug",
    "nspr",
    "nss",
    "submodule",
    "symlink",
    "try_task_config",
    "wpt",
]


@pytest.fixture
def get_failing_check_diff() -> Callable:
    """Factory providing a check-failing diff.

    See FAILING_CHECK_TYPES for the list of commit types available for request.

    For convenience, a "valid" case is also available.
    """

    diffs = {
        "nspr": PATCH_NSPR_DIFF,
        "nss": PATCH_NSS_DIFF,
        "submodule": PATCH_SUBMODULE_DIFF,
        "symlink": PATCH_SYMLINK_DIFF,
        "try_task_config": PATCH_TRY_TASK_CONFIG_DIFF,
        "valid": PATCH_DIFF,
        "valid2": PATCH_DIFF_2,
        # WPTCheck verifies that commits from wptsync@mozilla only touch paths in
        # WPT_SYNC_ALLOWED_PATHS_RE (currently a subset of testing/web-platform/).
        "wpt": PATCH_DIFF,
    }

    def _diff(name: str) -> str | None:
        if name in ["nobug"]:
            # Some actions are bad not because of their diff, but some other metadata of the
            # patch (e.g. no bug in the commit message). We use an innocuous diff for them.
            name = "valid"
        diff = diffs.get(name)
        assert diff, f"get_failing_check_diff doesn't know {name}"
        return diff

    return _diff


@pytest.fixture
def get_failing_check_commit_reason(get_failing_check_diff) -> Callable:
    """Factory providing a check-failing commit, and the expected failure reason.

    See FAILING_CHECK_TYPES for the list of commit types available for request.

    For convenience, a "valid" case is also available.
    """
    commit_reasons = {
        # CommitMessagesCheck
        "nobug": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "commit message without bug info",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision needs 'Bug N' or 'No bug' in the commit message: commit message without bug info",
        ),
        # PreventNSPRNSSCheck
        "nspr": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: commit with NSPR changes",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision makes changes to restricted directories:",
        ),
        # PreventNSPRNSSCheck
        "nss": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: commit with NSS changes",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision makes changes to restricted directories:",
        ),
        # PreventSubmodulesCheck
        "submodule": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: commit with .gitmodules changes",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision introduces a Git submodule into the repository.",
        ),
        # PreventSymlinksCheck
        "symlink": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: commit with symlink",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision introduces symlinks in the files ",
        ),
        # TryTaskConfigCheck
        "try_task_config": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "No bug: commit with try_task_config.json",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision introduces the `try_task_config.json` file.",
        ),
        # One that works, for reference.
        "valid": (
            {
                "author": "Test User <test@example.com>",
                "commitmsg": "no bug: commit message without bug info",
                # diff should get added by the test using get_failing_check_diff
            },
            "",
        ),
        # WPTSyncCheck
        "wpt":
        # WPTCheck verifies that commits from wptsync@mozilla only touch paths in
        # WPT_SYNC_ALLOWED_PATHS_RE (currently a subset of testing/web-platform/).
        (
            {
                "author": "WPT Sync Bot <wptsync@mozilla.com>",
                "commitmsg": "No bug: WPT commit with non-WPTSync changes",
                # diff should get added by the test using get_failing_check_diff
            },
            "Revision has WPTSync bot making changes to disallowed files ",
        ),
    }

    def failing_check_commit_reason_factory(name: str) -> tuple[dict, str] | None:
        cr = commit_reasons.get(name)
        assert cr, f"get_failing_check_commit_reason doesn't know {name}"
        cr[0]["diff"] = get_failing_check_diff(name)
        return cr

    return failing_check_commit_reason_factory


@pytest.fixture
def extract_email() -> Callable:
    def _extract_email(author_string: str) -> str:
        """Extract the email address from a string containing it between angle brackets."""
        author_match = re.search("<([^>]*@[^>]*)>", author_string)
        if not author_match:
            raise AssertionError(f"Can't parse email from `{author_string}`")

        author_email = author_match[1]
        return author_email

    return _extract_email


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
    hg_clone: os.PathLike,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    automation_enabled: bool = True,
    force_push: bool = False,
    hooks_enabled: bool = True,
    hooks: list[str] | None = None,
    hooks_to_disable: list[str] | None = None,
    name: str = "",
    push_target: str = "",
) -> Repo:
    params = {
        "name": name or "mozilla-central-hg",
        "pull_path": hg_server,
        "push_path": hg_server,
        "required_permission": SCM_LEVEL_3,
        "system_path": hg_clone.strpath,
        "url": hg_server,
        # The option below can be overriden in the parameters
        "approval_required": approval_required,
        "autoformat_enabled": autoformat_enabled,
        "automation_enabled": automation_enabled,
        "force_push": force_push,
        "hooks_enabled": hooks_enabled,
        # We only set "hooks" below, if not empty.
        "push_target": push_target,
    }
    if hooks:
        # There's a sane default in the fixture we call, so we don't want to override it
        # with None if nothing explicit it given.
        params["hooks"] = hooks

    repo = Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        **params,
    )
    if hooks_to_disable:
        repo.hooks = [h for h in repo.hooks if h not in hooks_to_disable]

    repo.save()
    return repo


@pytest.mark.django_db
def git_repo_mc(
    git_repo: pathlib.Path,
    tmp_path: pathlib.Path,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    automation_enabled: bool = True,
    force_push: bool = False,
    hooks_enabled: bool = True,
    hooks: list[str] | None = None,
    hooks_to_disable: list[str] | None = None,
    name: str = "",
    push_target: str = "",
) -> Repo:
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir(exist_ok=True)

    params = {
        "name": name or "mozilla-central-git",
        "pull_path": str(git_repo),
        "push_path": str(git_repo),
        "required_permission": SCM_LEVEL_3,
        "system_path": repos_dir / "git_repo",
        "url": str(git_repo),
        # The option below can be overriden in the parameters
        "approval_required": approval_required,
        "autoformat_enabled": autoformat_enabled,
        "automation_enabled": automation_enabled,
        "force_push": force_push,
        "hooks_enabled": hooks_enabled,
        # We only set "hooks" below, if not empty.
        "push_target": push_target,
    }
    if hooks:
        # There's a sane default in the fixture we call, so we don't want to override it
        # with None if nothing explicit it given.
        params["hooks"] = hooks

    repo = Repo.objects.create(
        scm_type=SCM_TYPE_GIT,
        **params,
    )
    if hooks_to_disable:
        repo.hooks = [h for h in repo.hooks if h not in hooks_to_disable]

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
    hg_clone: os.PathLike,
) -> Callable:
    def factory(
        scm_type: str,
        *,
        approval_required: bool = False,
        autoformat_enabled: bool = True,
        automation_enabled: bool = True,
        force_push: bool = False,
        hooks_enabled: bool = True,
        hooks: list[str] | None = None,
        hooks_to_disable: list[str] | None = None,
        name: str = "",
        push_target: str = "",
    ) -> Repo:
        # The BMO reference check 1) requires access to a BMO instance to test with and
        # 2) is only needed for Try. We disable it here to be closer to a normal MC
        # repo.
        default_hooks_to_disable = ["BugReferencesCheck"]

        params = {
            "approval_required": approval_required,
            "autoformat_enabled": autoformat_enabled,
            "automation_enabled": automation_enabled,
            "hooks_enabled": hooks_enabled,
            "hooks": hooks or [],
            "hooks_to_disable": hooks_to_disable or default_hooks_to_disable,
            "force_push": force_push,
            "name": name,
            "push_target": push_target,
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
def hg_clone(hg_server: str, tmpdir: os.PathLike) -> os.PathLike:
    clone_dir = tmpdir.join("hg_clone")
    subprocess.run(["hg", "clone", hg_server, clone_dir.strpath], check=True)
    return clone_dir


@pytest.fixture
def hg_test_bundle() -> pathlib.Path:
    return settings.BASE_DIR / "api" / "tests" / "data" / "test-repo.bundle"


@pytest.fixture
def hg_server(hg_test_bundle: pathlib.Path, tmpdir: os.PathLike, worker_id: str):
    """Start a Mercurial server on a unique port per worker for parallel test execution."""
    # Use worker_id to generate unique port for each parallel worker
    if worker_id == "master":
        # Not running in parallel, use default port
        port = 8000
    else:
        # Extract worker number (e.g., "gw0" -> 0, "gw1" -> 1)
        worker_num = int(worker_id.replace("gw", ""))
        port = 8000 + worker_num

    hg_url = f"http://localhost:{port}"

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
            str(port),
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
            break
        except Exception:
            time.sleep(1)

    yield hg_url
    serve.kill()


@pytest.fixture
def create_scm_commit(
    create_git_commit: Callable, create_hg_commit: Callable
) -> Callable:
    def _create_commit(clone_path: Path) -> str:
        if GitSCM.repo_is_supported(str(clone_path)):
            return create_git_commit(clone_path)
        if HgSCM.repo_is_supported(str(clone_path)):
            return create_hg_commit(clone_path)
        raise ValueError(f"Cannot determine which SCM to use for {clone_path}")

    return _create_commit


@pytest.fixture
def create_git_commit(request: pytest.FixtureRequest) -> Callable:
    def _create_git_commit(clone_path: Path) -> str:
        new_file = clone_path / str(uuid.uuid4())
        new_file.write_text(request.node.name, encoding="utf-8")

        subprocess.run(["git", "add", new_file.name], cwd=str(clone_path), check=True)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"No bug: adding {new_file}",
                "--author",
                f"{request.node.name} <pytest@lando>",
            ],
            cwd=str(clone_path),
            check=True,
        )

        return new_file

    return _create_git_commit


@pytest.fixture
def create_hg_commit(request: pytest.FixtureRequest) -> Callable:
    def _create_hg_commit(clone_path: Path) -> str:
        new_file = clone_path / str(uuid.uuid4())
        new_file.write_text(request.node.name, encoding="utf-8")

        subprocess.run(["hg", "addremove"], cwd=str(clone_path), check=True)
        subprocess.run(
            [
                "hg",
                "commit",
                "-m",
                f"No bug: adding {new_file}",
            ],
            cwd=str(clone_path),
            check=True,
        )

        return new_file

    return _create_hg_commit


@pytest.fixture
def to_profile_permissions() -> Callable:
    """Convert a list of un-namespaced permissions strings to a list of profile Permissions."""

    def _to_profile_permissions(permissions: list[str]) -> list[Permission]:
        all_perms = Profile.get_all_scm_permissions()

        return [all_perms[p] for p in permissions]

    return _to_profile_permissions


@pytest.fixture
def conduit_permissions(to_profile_permissions: Callable) -> list[Permission]:
    permissions = (
        "scm_level_1",
        "scm_level_2",
        "scm_level_3",
        "scm_conduit",
    )
    return to_profile_permissions(permissions)


@pytest.fixture
def user_plaintext_password():
    return "test_password"


@pytest.fixture
def landing_worker_instance(mocked_repo_config) -> Callable:
    def _instance(scm, **kwargs) -> Worker:
        worker = Worker.objects.create(sleep_seconds=0, scm=scm, **kwargs)
        worker.applicable_repos.set(Repo.objects.filter(scm_type=scm))
        return worker

    return _instance


@pytest.fixture
def scm_user() -> Callable:
    def scm_user(
        perms: list[Permission],
        password: str = "password",
        group_perms: list[Permission] | None = None,
    ) -> User:
        """Return a user with the selected Permissions and password."""
        user = User.objects.create_user(
            username="test_user",
            password=password,
            email="testuser@example.org",
        )

        user.profile = Profile(user=user, userinfo={"name": "test user"})

        for permission in perms:
            user.user_permissions.add(permission)

        if group_perms:
            group = Group.objects.create(
                name="test group",
            )
            group.permissions.set(group_perms)
            user.groups.add(group)

        user.save()
        user.profile.save()

        return user

    return scm_user


@pytest.fixture
def user_phab_api_key():
    return "api-123456789012345678901234567x"


@pytest.fixture
def user(
    scm_user: Callable,
    user_plaintext_password: str,
    conduit_permissions: list[str],
    user_phab_api_key: str,
) -> User:
    """A User with all SCM permissions levels."""
    user = scm_user(conduit_permissions, user_plaintext_password)
    user.profile.save_phabricator_api_key(user_phab_api_key)

    user.save()
    user.profile.save()

    return user


@pytest.fixture
def make_superuser() -> Callable:
    def _make_superuser(user: User) -> User:
        user.is_superuser = True
        user.save()

        # Re-retrieve the updated user to refresh the user permissions.
        # `refresh_from_db` (empirically), is not sufficient here.
        return User.objects.get(id=user.id)

    return _make_superuser


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


@pytest.fixture
def commit_maps(git_repo) -> list[CommitMap]:
    for git_hash, hg_hash in (
        ("a" * 39 + "b", "b" * 39 + "c"),
        ("a" * 40, "b" * 40),
        ("c" * 40, "d" * 40),
        ("e" * 40, "f" * 40),
    ):
        CommitMap.objects.create(
            git_hash=git_hash, hg_hash=hg_hash, git_repo_name=git_repo.name
        )
    return list(CommitMap.objects.all().order_by("id"))


@pytest.fixture
def mock_phab_trigger_repo_update_apply_async(monkeypatch: pytest.MonkeyPatch):
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.utils.tasks.phab_trigger_repo_update.apply_async",
        mock_trigger_update,
    )

    return mock_trigger_update


@pytest.fixture
def make_landing_job(repo_mc: Repo) -> Callable:
    def landing_job_factory(
        *,
        revisions: list[Revision] | None = None,
        landing_path: Iterable[tuple[int, int]] = ((1, 1),),
        requester_email: str = "tuser@example.com",
        status: str | None = None,
        target_repo: str | None = None,
        **kwargs,
    ) -> LandingJob:
        """Create a landing job with revisions.

        If revisions is None, a set of revisions will be built from landing_paths.
        """
        if not target_repo:
            target_repo = repo_mc(SCM_TYPE_GIT)

        job_params = {
            "requester_email": requester_email,
            "status": status,
            "target_repo": target_repo,
            **kwargs,
        }
        if not revisions:
            revisions = []
            for revision_id, diff_id in landing_path:
                revision = Revision.one_or_none(revision_id=revision_id)
                if not revision:
                    revision = Revision(revision_id=revision_id)
                revision.diff_id = diff_id
                revisions.append(revision)
            for revision in revisions:
                revision.save()
        job = add_job_with_revisions(revisions, **job_params)
        return job

    return landing_job_factory


@pytest.fixture
def new_treestatus_tree():
    """Create a new tree in the test db."""

    def _new_tree(
        tree: str = "",
        status: TreeStatus = TreeStatus.OPEN,
        reason: str = "",
        motd: str = "",
    ):
        new_tree = Tree.objects.create(
            tree=tree,
            status=status,
            reason=reason,
            message_of_the_day=motd,
        )
        return new_tree

    return _new_tree


@pytest.fixture
def active_mock() -> Callable:
    def _active_mock(obj: object, method: str) -> mock.MagicMock:
        """Mock a method without preventing its side-effect from happening."""
        original = getattr(obj, method)
        mock_method = mock.MagicMock()
        mock_method.side_effect = original
        setattr(obj, method, mock_method)
        return mock_method

    return _active_mock


class MockResponse:
    """Mock response class to satisfy some requirements of tests.

    Headers keys will be normalised to all-lowercase.
    """

    _json: dict | list | None = None

    def __init__(
        self,
        *,
        json_dict: dict | None = None,
        text: str | None = None,
        status_code: int = 200,
        headers: dict | None = None,
    ):
        if json_dict and text:
            raise Exception("MockResponse can't specify json and text at the same time")

        self.status_code = status_code

        headers = headers or {}
        self.headers = {}
        # Lower case all provided headers.
        for hkey in headers:
            self.headers[hkey.lower()] = headers[hkey]

        # Set a reasonable content-type header value.
        if not self.headers.get("content_type"):
            self.headers["content_type"] = (
                "text/plain"
                if text
                else (
                    "application/json"
                    if status_code < 400
                    else "application/problem+json"
                )
            )

        try:
            self._json = json_dict or json.loads(text or "")
        except json.JSONDecodeError:
            pass
        self.text = text or json.dumps(json_dict)

    def json(self) -> dict | list:
        return self._json

    @property
    def content_type(self):
        return self.headers["content_type"]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(f"Status code {self.status_code} in MockResponse")


@pytest.fixture
def mock_response() -> Callable:
    def _mock_response(
        *,
        json_dict: dict | None = None,
        text: str | None = None,
        status_code: int = 200,
        headers: dict | None = None,
    ) -> MockResponse:
        return MockResponse(
            json_dict=json_dict, text=text, status_code=status_code, headers=headers
        )

    return _mock_response


@pytest.fixture()
def ninja_api_client() -> Callable:
    """Fixture to create a test client for the API."""

    # XXX If we pass the API directly, we get an error if we want to use this client
    # more than once (regardless of the scope of the fixture), as follows:
    #
    #    Looks like you created multiple NinjaAPIs or TestClients
    #    To let ninja distinguish them you need to set either unique version or urls_namespace
    #     - NinjaAPI(..., version='2.0.0')
    #     - NinjaAPI(..., urls_namespace='otherapi')
    #
    # Passing the pre-existing router to the TestClient instead, works. However, getting the
    # router is not golden-path.
    #
    def _ninja_api_client(api: NinjaAPI) -> TestClient:
        return TestClient(api.default_router)

    return _ninja_api_client
