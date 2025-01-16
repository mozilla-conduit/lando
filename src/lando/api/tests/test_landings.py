import io
import pathlib
import unittest.mock as mock
from collections.abc import Callable

import py
import pytest

from lando.api.legacy.workers.landing_worker import (
    AUTOFORMAT_COMMIT_MESSAGE,
    LandingWorker,
)
from lando.main.models import SCM_LEVEL_3, Repo
from lando.main.models.landing_job import (
    LandingJob,
    LandingJobStatus,
    add_job_with_revisions,
)
from lando.main.models.revision import Revision
from lando.main.scm import SCM_TYPE_HG
from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.consts import SCM_TYPE_GIT
from lando.main.scm.git import GitSCM
from lando.main.scm.hg import HgSCM, LostPushRace
from lando.utils import HgPatchHelper


@pytest.fixture
@pytest.mark.django_db
def create_patch_revision(normal_patch):
    """A fixture that fake uploads a patch"""

    normal_patch_0 = normal_patch(0)

    def _create_patch_revision(number, patch=normal_patch_0):
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


LARGE_UTF8_THING = "😁" * 1000000

LARGE_PATCH = rf"""
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
+{LARGE_UTF8_THING}
""".lstrip()

PATCH_WITHOUT_STARTLINE = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()


PATCH_PUSH_LOSER = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Fail HG Import LOSE_PUSH_RACE
# Diff Start Line 8
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding one more line again
""".lstrip()

PATCH_FORMATTING_PATTERN_PASS = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add formatting config

diff --git a/.lando.ini b/.lando.ini
new file mode 100644
--- /dev/null
+++ b/.lando.ini
@@ -0,0 +1,3 @@
+[autoformat]
+enabled = True
+
diff --git a/mach b/mach
new file mode 100755
--- /dev/null
+++ b/mach
@@ -0,0 +1,30 @@
+#!/usr/bin/env python3
+# This Source Code Form is subject to the terms of the Mozilla Public
+# License, v. 2.0. If a copy of the MPL was not distributed with this
+# file, You can obtain one at http://mozilla.org/MPL/2.0/.
+
+# Fake formatter that rewrites text to mOcKiNg cAse
+
+import pathlib
+import sys
+
+HERE = pathlib.Path(__file__).resolve().parent
+
+def split_chars(string) -> list:
+    return [char for char in string]
+
+
+if __name__ == "__main__":
+    testtxt = HERE / "test.txt"
+    if not testtxt.exists():
+        sys.exit(0)
+    with testtxt.open() as f:
+        stdin_content = f.read()
+    stdout_content = []
+
+    for i, word in enumerate(split_chars(stdin_content)):
+        stdout_content.append(word.upper() if i % 2 == 0 else word.lower())
+
+    with testtxt.open("w") as f:
+        f.write("".join(stdout_content))
+    sys.exit(0)

""".lstrip()

PATCH_FORMATTING_PATTERN_FAIL = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add formatting config

diff --git a/.lando.ini b/.lando.ini
new file mode 100644
--- /dev/null
+++ b/.lando.ini
@@ -0,0 +1,3 @@
+[autoformat]
+enabled = True
+
diff --git a/mach b/mach
new file mode 100755
--- /dev/null
+++ b/mach
@@ -0,0 +1,9 @@
+#!/usr/bin/env python3
+# This Source Code Form is subject to the terms of the Mozilla Public
+# License, v. 2.0. If a copy of the MPL was not distributed with this
+# file, You can obtain one at http://mozilla.org/MPL/2.0/.
+
+# Fake formatter that fails to run.
+import sys
+sys.exit("MACH FAILED")
+

""".lstrip()

PATCH_FORMATTED_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
bug 123: add another file for formatting 1

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,4 @@
 TEST
+
+
+adding another line
""".lstrip()

PATCH_FORMATTED_2 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file for formatting 2

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -2,3 +2,4 @@ TEST

 
 adding another line
+add one more line
""".lstrip()  # noqa: W293

TESTTXT_FORMATTED_1 = b"""
TeSt


aDdInG AnOtHeR LiNe
""".lstrip()

TESTTXT_FORMATTED_2 = b"""
TeSt


aDdInG AnOtHeR LiNe
aDd oNe mOrE LiNe
""".lstrip()


@pytest.mark.django_db
def hg_repo_mc(
    hg_server: str,
    hg_clone: py.path,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    force_push: bool = False,
    push_target: str = "",
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
    ) -> Repo:
        params = {
            "approval_required": approval_required,
            "autoformat_enabled": autoformat_enabled,
            "force_push": force_push,
            "push_target": push_target,
        }

        if scm_type == SCM_TYPE_GIT:
            return git_repo_mc(git_repo, tmp_path, **params)
        elif scm_type == SCM_TYPE_HG:
            return hg_repo_mc(hg_server, hg_clone, **params)
        raise Exception(f"Unknown SCM Type {scm_type=}")

    return factory


@pytest.mark.parametrize(
    "repo_type,revisions_params",
    [
        # Git
        (
            SCM_TYPE_GIT,
            [
                (1, {"patch": None}),
                (2, {"patch": None}),
            ],
        ),
        (SCM_TYPE_GIT, [(1, {"patch": LARGE_PATCH})]),
        # Hg
        (
            SCM_TYPE_HG,
            [
                (1, {"patch": None}),
                (2, {"patch": None}),
            ],
        ),
        (SCM_TYPE_HG, [(1, {"patch": LARGE_PATCH})]),
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
    revisions_params,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)

    revisions = [
        create_patch_revision(number, **kwargs) for number, kwargs in revisions_params
    ]

    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job)
    assert job.status == LandingJobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job_with_force_push(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
):
    repo = repo_mc(repo_type, force_push=True)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions([create_patch_revision(1)], **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # We don't care about repo update in this test, however if we don't mock
    # this, the test will fail since there is no celery instance.
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock.MagicMock(),
    )

    scm.push = mock.MagicMock()
    assert worker.run_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == repo.url
    assert scm.push.call_args[1] == {"push_target": "", "force_push": True}


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job_with_bookmark(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
):
    repo = repo_mc(repo_type, push_target="@")
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions([create_patch_revision(1)], **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # We don't care about repo update in this test, however if we don't mock
    # this, the test will fail since there is no celery instance.
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock.MagicMock(),
    )

    scm.push = mock.MagicMock()
    assert worker.run_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == repo.url
    assert scm.push.call_args[1] == {"push_target": "@", "force_push": False}


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_no_diff_start_line(
    repo_mc,
    treestatusdouble,
    create_patch_revision,
    caplog,
    repo_type: str,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)

    job_params = {
        "id": 1234,
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(
        [create_patch_revision(1, patch=PATCH_WITHOUT_STARTLINE)], **job_params
    )

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    assert worker.run_job(job)
    assert job.status == LandingJobStatus.FAILED
    assert "Patch without a diff start line." in caplog.text


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_lose_push_race(
    monkeypatch,
    repo_mc,
    treestatusdouble,
    create_patch_revision,
    repo_type: str,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "id": 1234,
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(
        [create_patch_revision(1, patch=PATCH_PUSH_LOSER)], **job_params
    )

    mock_push = mock.MagicMock()
    mock_push.side_effect = (
        LostPushRace(["testing_args"], "testing_out", "testing_err", "testing_msg"),
    )
    monkeypatch.setattr(
        scm,
        "push",
        mock_push,
    )
    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    assert not worker.run_job(job)
    assert job.status == LandingJobStatus.DEFERRED


@pytest.mark.parametrize(
    "repo_type, expected_error_log",
    [
        (SCM_TYPE_GIT, "Rejected hunk"),
        (SCM_TYPE_HG, "hunks FAILED"),
    ],
)
@pytest.mark.django_db
def test_merge_conflict(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    caplog,
    repo_type: str,
    expected_error_log: str,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)

    job_params = {
        "id": 1234,
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(
        [
            create_patch_revision(1, patch=PATCH_FORMATTED_2),
        ],
        **job_params,
    )

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # We don't care about repo update in this test, however if we don't mock
    # this, the test will fail since there is no celery instance.
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock.MagicMock(),
    )

    assert worker.run_job(job)
    assert job.status == LandingJobStatus.FAILED

    assert expected_error_log in caplog.text

    assert job.error_breakdown, "No error breakdown added to job"
    assert job.error_breakdown.get(
        "rejects_paths"
    ), "Empty or missing reject information in error breakdown"
    failed_paths = [p["path"] for p in job.error_breakdown["failed_paths"]]
    assert set(failed_paths) == set(
        job.error_breakdown["rejects_paths"].keys()
    ), "Mismatch between failed_paths and rejects_paths"
    for fp in failed_paths:
        assert job.error_breakdown["rejects_paths"][fp].get(
            "path"
        ), f"Empty or missing reject path for failed path {fp}"
        assert job.error_breakdown["rejects_paths"][fp].get(
            "content"
        ), f"Empty or missing reject content for failed path {fp}"


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_failed_landing_job_notification(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
):
    """Ensure that a failed landings triggers a user notification."""
    repo = repo_mc(repo_type, approval_required=True, autoformat_enabled=False)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    # Mock `scm.update_repo` so we can force a failed landing.
    mock_update_repo = mock.MagicMock()
    mock_update_repo.side_effect = Exception("Forcing a failed landing")
    monkeypatch.setattr(scm, "update_repo", mock_update_repo)

    revisions = [
        create_patch_revision(1),
        create_patch_revision(2),
    ]
    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.notify_user_of_landing_failure",
        mock_notify,
    )

    assert worker.run_job(job)
    assert job.status == LandingJobStatus.FAILED
    assert mock_notify.call_count == 1


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_format_patch_success_unchanged(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    normal_patch,
    repo_type: str,
):
    """Tests automated formatting happy path where formatters made no changes."""
    repo = repo_mc(repo_type, autoformat_enabled=True)
    treestatusdouble.open_tree(repo.name)

    revisions = [
        create_patch_revision(1, patch=PATCH_FORMATTING_PATTERN_PASS),
        create_patch_revision(2, patch=normal_patch(2)),
    ]
    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job)
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."
    assert (
        job.formatted_replacements is None
    ), "Autoformat making no changes should leave `formatted_replacements` empty."


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_format_single_success_changed(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
):
    """Test formatting a single commit via amending."""
    repo = repo_mc(repo_type, autoformat_enabled=True)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    # Push the `mach` formatting patch.
    with scm.for_push("test@example.com"):
        ph = HgPatchHelper(io.StringIO(PATCH_FORMATTING_PATTERN_PASS))
        scm.apply_patch(
            ph.get_diff(),
            ph.get_commit_description(),
            ph.get_header("User"),
            ph.get_header("Date"),
        )
        scm.push(repo.push_path)
        pre_landing_tip = scm.head_ref()

    # Upload a patch for formatting.
    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(
        [create_patch_revision(2, patch=PATCH_FORMATTED_1)], **job_params
    )

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job), "`run_job` should return `True` on a successful run."
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with scm.for_push(job.requester_email):
        # Get the commit message.
        desc = _scm_get_last_commit_message(scm)

        # Get the content of the file after autoformatting.
        tip_content = scm.read_checkout_file("test.txt").encode("utf-8")

        # Get the hash behind the tip commit.
        hash_behind_current_tip = _scm_get_previous_hash(scm)

    assert tip_content == TESTTXT_FORMATTED_1, "`test.txt` is incorrect in base commit."

    assert (
        desc == "bug 123: add another file for formatting 1"
    ), "Autoformat via amend should not change commit message."

    assert (
        hash_behind_current_tip == pre_landing_tip
    ), "Autoformat via amending should only land a single commit."


def _scm_get_previous_hash(scm: AbstractSCM) -> str:
    if scm.scm_type() == SCM_TYPE_HG:
        return HgSCM.run_hg(scm, ["log", "-r", "tip^", "-T", "{node}"]).decode("utf-8")
    return GitSCM._git_run("rev-parse", "HEAD^", cwd=scm.path)


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_format_stack_success_changed(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
):
    """Test formatting a stack via an autoformat tip commit."""
    repo = repo_mc(repo_type, autoformat_enabled=True)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    revisions = [
        create_patch_revision(1, patch=PATCH_FORMATTING_PATTERN_PASS),
        create_patch_revision(2, patch=PATCH_FORMATTED_1),
        create_patch_revision(3, patch=PATCH_FORMATTED_2),
    ]
    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job), "`run_job` should return `True` on a successful run."
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with scm.for_push(job.requester_email):
        # Get the commit message.
        desc = _scm_get_last_commit_message(scm)

        # Get the content of the file after autoformatting.
        rev3_content = scm.read_checkout_file("test.txt").encode("utf-8")

    assert (
        rev3_content == TESTTXT_FORMATTED_2
    ), "`test.txt` is incorrect in base commit."

    assert (
        "# ignore-this-changeset" in desc
    ), "Commit message for autoformat commit should contain `# ignore-this-changeset`."

    assert desc == AUTOFORMAT_COMMIT_MESSAGE.format(
        bugs="Bug 123"
    ), "Autoformat commit has incorrect commit message."


def _scm_get_last_commit_message(scm: AbstractSCM) -> str:
    if scm.scm_type() == SCM_TYPE_HG:
        return HgSCM.run_hg(scm, ["log", "-r", "tip", "-T", "{desc}"]).decode("utf-8")
    return GitSCM._git_run("log", "--pretty=%B", "HEAD^..", cwd=scm.path)


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_format_patch_fail(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    normal_patch,
    repo_type: str,
):
    """Tests automated formatting failures before landing."""
    repo = repo_mc(repo_type, autoformat_enabled=True)
    treestatusdouble.open_tree(repo.name)

    revisions = [
        create_patch_revision(1, patch=PATCH_FORMATTING_PATTERN_FAIL),
        create_patch_revision(2, patch=normal_patch(0)),
        create_patch_revision(3, patch=normal_patch(1)),
    ]
    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.notify_user_of_landing_failure",
        mock_notify,
    )

    assert not worker.run_job(
        job
    ), "`run_job` should return `False` when autoformatting fails."
    assert (
        job.status == LandingJobStatus.FAILED
    ), "Failed autoformatting should set `FAILED` job status."
    assert (
        "Lando failed to format your patch" in job.error
    ), "Error message is not set to show autoformat caused landing failure."
    assert (
        mock_notify.call_count == 1
    ), "User should be notified their landing was unsuccessful due to autoformat."


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
    ],
)
@pytest.mark.django_db
def test_format_patch_no_landoini(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    repo_type: str,
):
    """Tests behaviour of Lando when the `.lando.ini` file is missing."""
    repo = repo_mc(repo_type, autoformat_enabled=True)
    treestatusdouble.open_tree(repo.name)

    revisions = [
        # Patch=None lets create_patch_revision determine the patch to use based on the
        # revision number.
        create_patch_revision(1, patch=None),
        create_patch_revision(2, patch=None),
    ]
    job_params = {
        "status": LandingJobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    worker = LandingWorker(repos=Repo.objects.all(), sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.notify_user_of_landing_failure",
        mock_notify,
    )

    assert worker.run_job(job)
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Missing `.lando.ini` should not inhibit landing."
    assert (
        mock_notify.call_count == 0
    ), "Should not notify user of landing failure due to `.lando.ini` missing."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."


# bug 1893453
@pytest.mark.xfail
@pytest.mark.django_db
def test_landing_job_revisions_sorting(
    create_patch_revision,
):
    revisions = [
        create_patch_revision(1),
        create_patch_revision(2),
        create_patch_revision(3),
    ]
    job_params = {
        "status": LandingJobStatus.SUBMITTED,
        "requester_email": "test@example.com",
        "repository_name": "mozilla-central",
        "attempts": 1,
    }
    job = add_job_with_revisions(revisions, **job_params)

    assert list(job.revisions.all()) == revisions
    new_ordering = [revisions[2], revisions[0], revisions[1]]
    job.sort_revisions(new_ordering)
    job.save()
    job = LandingJob.objects.get(id=job.id)
    assert list(job.revisions.all()) == new_ordering
