import io
import itertools
import re
import subprocess
import unittest.mock as mock
from pathlib import Path
from typing import Callable

import pytest

from lando.api.legacy.workers.landing_worker import (
    AUTOFORMAT_COMMIT_MESSAGE,
    LandingWorker,
)
from lando.api.tests.mocks import TreeStatusDouble
from lando.conftest import FAILING_CHECK_TYPES
from lando.main.models import (
    JobStatus,
    LandingJob,
    Repo,
    RevisionLandingJob,
)
from lando.main.scm import SCMType
from lando.main.scm.exceptions import SCMInternalServerError
from lando.main.scm.git import GitSCM
from lando.main.scm.helpers import HgPatchHelper
from lando.main.scm.hg import LostPushRace
from lando.pushlog.models.commit import Commit
from lando.pushlog.models.push import Push

LARGE_UTF8_THING = "😁" * 1000000

LARGE_PATCH = rf"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
No bug: add another line with utf-8

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+{LARGE_UTF8_THING}
""".lstrip()

BINARY_PATCH = """
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
No bug: add a binary file

diff --git a/binary b/binary
new file mode 100644
index 0000000000000000000000000000000000000000..0a4a1abd1fe6031fedcd6c37a8ae159b4815dbf1
GIT binary patch
literal 68
zc$@)50K5MhMc<=BLKstkXJsT7RIY2HuAtX}0dvKNfMp^@U!h!sfdYnwR$o?7IN*n{
af&r|$f$<+hwsrnO@__&U{{;X4B>w*ZZ6WCZ

literal 0
Hc$@<O00001


""".lstrip()

PATCH_WITHOUT_STARTLINE = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
No bug: add another line without startline.
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
No bug: add one more line.
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
No bug: add formatting config

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
No bug: add formatting config

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
no bug: add another file for formatting 2

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -2,3 +2,4 @@ TEST

 
 adding another line
+add one more line
""".lstrip()  # noqa: W293

PATCH_CHANGE_MISSING_CONTENT = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,1 @@
-LINE THAT IS NOT HERE
+adding different line
""".lstrip()  # noqa: W293

PATCH_BINARY_GITATTRIBUTES = r"""
# HG changeset patch
# User Local Dev <local-dev@mozilla.bugs>
# Date 1756103176 +0000
# Diff Start Line 8
almost-not-binary: add testcase for Bug 1984942

Differential Revision: http://phabricator.test/D71

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


TESTTXT_FORMATTED_1 = b"""
TeSt


aDdInG AnOtHeR LiNe
""".lstrip()

TESTTXT_FORMATTED_2 = b"""
TeSt


aDdInG AnOtHeR LiNe
aDd oNe mOrE LiNe
""".lstrip()

TRY_TASK_CONFIG_DIFF_SNIPPET = """
--- /dev/null
+++ b/try_task_config.json
@@ -0,0 +1 @@
+{{"parameters": {{"optimize_target_tasks": true, "target_tasks_method": "codereview", "try_mode": "try_task_config", "try_task_config": {{"github": {{"pull_number": 1, "pull_head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "repo_url": "{}", "branch": "main"}}}}}}, "version": 2}}
\\ No newline at end of file
""".lstrip()


@pytest.mark.parametrize(
    "target_commit_hash, supports_3way, base_revision, base_exists, expected",
    [
        # A known target commit short-circuits before consulting the SCM.
        pytest.param("deadbeef", True, "abc123", True, None, id="target-commit-hash"),
        # An SCM that can't rebase always applies at the tip.
        pytest.param("", False, "abc123", True, None, id="scm-unsupported"),
        # The recorded base is used when it exists in the repo.
        pytest.param("", True, "abc123", True, "abc123", id="base-present"),
        # A recorded base missing from the repo falls back to the tip.
        pytest.param("", True, "abc123", False, None, id="base-missing"),
        # No recorded base means there is nothing to reconstruct onto.
        pytest.param("", True, "", False, None, id="no-recorded-base"),
    ],
)
@pytest.mark.django_db
def test_determine_rebase_base(
    git_landing_worker: LandingWorker,
    target_commit_hash: str,
    supports_3way: bool,
    base_revision: str,
    base_exists: bool,
    expected: str | None,
):
    """`determine_rebase_base` returns the base only when every condition holds."""
    job = mock.Mock(target_commit_hash=target_commit_hash)
    job.revisions.first.return_value = mock.Mock(base_revision=base_revision)
    scm = mock.Mock()
    # `supports_3way_apply` is a property, so assign the value directly.
    scm.supports_3way_apply = supports_3way
    scm.commit_exists.return_value = base_exists

    assert git_landing_worker.determine_rebase_base(job, scm) == expected, (
        "`determine_rebase_base` should only return a base when all conditions hold."
    )


@pytest.mark.parametrize(
    "repo_type,revisions_params",
    [
        # Git
        (
            SCMType.GIT,
            [
                (1, {"patch": None}),
                (2, {"patch": None}),
            ],
        ),
        (SCMType.GIT, [(1, {"patch": LARGE_PATCH})]),
        (SCMType.GIT, [(1, {"patch": PATCH_BINARY_GITATTRIBUTES})]),
        (SCMType.GIT, [(1, {"patch": BINARY_PATCH})]),
        # Hg
        (
            SCMType.HG,
            [
                (1, {"patch": None}),
                (2, {"patch": None}),
            ],
        ),
        (SCMType.HG, [(1, {"patch": LARGE_PATCH})]),
        (SCMType.HG, [(1, {"patch": PATCH_BINARY_GITATTRIBUTES})]),
        (SCMType.HG, [(1, {"patch": BINARY_PATCH})]),
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job(
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,
    mock_phab_trigger_repo_update_apply_async: mock.Mock,
    create_patch_revision: Callable,
    make_landing_job: Callable,
    repo_type: str,
    revisions_params: list,
    get_landing_worker: Callable,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)

    revisions = [
        create_patch_revision(number, **kwargs) for number, kwargs in revisions_params
    ]

    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)

    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40
    assert mock_phab_trigger_repo_update_apply_async.call_count == 1, (
        "Successful landing should trigger Phab repo update."
    )

    # The diff_id is not set for landings not created from Phabricator transplants.
    assert job.landed_revisions == {r.id: None for r in revisions}, (
        "Incorrect mapping of internal revision IDs to diff ID"
    )

    new_commit_count = Commit.objects.filter(repo=repo).count()
    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_commit_count == len(revisions), (
        "Incorrect number of additional commits in the PushLog"
    )
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"


@mock.patch("lando.utils.github.GitHubAPI")
@pytest.mark.django_db
def test_integrated_execute_job_pull_request(
    GitHubAPI: mock.Mock,
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,
    create_pull_request_revision: Callable,
    make_landing_job: Callable,
    git_patch: Callable,
    get_landing_worker: Callable,
):
    """
    Test Pull Request landings.

    CAVEAT:
    * This only tests the local preparation of the push, as all GitHub interactions are
    mocked.
    * This doesn't re-test side effects already tested in test_integrated_execute_job.
    """
    pr_number = 1
    repo_type = SCMType.GIT
    repo: Repo = repo_mc(repo_type)
    repo.is_phabricator_repo = False
    repo.pr_enabled = True

    treestatusdouble.open_tree(repo.name)

    # We use git_patch(1) here, as it inserts a line in the middle of an existing file,
    # potentially triggering bug 2002094.
    revisions = [create_pull_request_revision(pr_number, git_patch(1))]

    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
        "is_pull_request_job": True,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)

    assert job.status == JobStatus.LANDED, job.error
    assert len(job.landed_commit_id) == 40

    # Check attempts to interact with GitHub.
    assert GitHubAPI.mock_calls, "GitHubAPI wasn't used."
    did_comment = False
    did_close = False
    for kall in GitHubAPI.mock_calls:
        if kall == mock.call().post(mock.ANY, json={"body": mock.ANY}):
            if (
                f"/issues/{pr_number}/comments" in kall[1][0]
                and "Pull request closed by commit" in kall[2]["json"]["body"]
            ):
                did_comment = True
        elif kall == mock.call().post(mock.ANY, json={"state": "closed"}):
            if (
                f"/pulls/{pr_number}" in kall[1][0]
                and kall[2]["json"]["state"] == "closed"
            ):
                did_close = True

    assert did_comment, "Successful landing did not add comment to PR"
    assert did_close, "Successful landing did not close PR"


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_revisionlandingjob_commit_ids_updated_on_success(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    repo_type: str,
):
    """Ensure landed commit SHAs are copied onto RevisionLandingJob rows."""
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)

    revisions = [
        create_patch_revision(1, patch=None),
        create_patch_revision(2, patch=None),
    ]
    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.LANDED

    revision_jobs = list(
        RevisionLandingJob.objects.filter(landing_job=job).order_by("index")
    )
    assert len(revision_jobs) == len(revisions)

    ordered_revisions = list(job.revisions)
    for revision, revision_job in zip(ordered_revisions, revision_jobs, strict=False):
        assert revision.commit_id, "`commit_id` should be set on `Revision` object."
        assert revision_job.commit_id, (
            "`commit_id` should be set on `RevisionLandingJob` object."
        )


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_revisionlandingjob_commit_ids_unset_without_landing(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    repo_type: str,
):
    """Ensure `commit_id` is not tracked for incomplete job."""
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=[create_patch_revision(1)], **job_params)

    scm.push = mock.MagicMock(side_effect=SCMInternalServerError("push failed", "500"))

    worker = get_landing_worker(repo_type)
    assert not worker.run_job(job)
    assert job.status == JobStatus.DEFERRED

    revision_jobs = list(
        RevisionLandingJob.objects.filter(landing_job=job).order_by("index")
    )
    assert len(revision_jobs) == 1

    revision = job.revisions.first()
    assert revision.commit_id, "`commit_id` should still be set on `Revision` object."
    assert revision_jobs[0].commit_id is None, (
        "`commit_id` should not be set for un-landed job."
    )


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job_with_force_push(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    repo_type: str,
):
    repo = repo_mc(repo_type, force_push=True)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=[create_patch_revision(1)], **job_params)

    scm.push = mock.MagicMock()

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)

    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == repo.url
    assert scm.push.call_args[1] == {"push_target": "", "force_push": True}


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job_with_bookmark(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    repo_type: str,
):
    repo = repo_mc(repo_type, push_target="@")
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=[create_patch_revision(1)], **job_params)

    scm.push = mock.MagicMock()
    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert scm.push.call_count == 1
    assert len(scm.push.call_args) == 2
    assert len(scm.push.call_args[0]) == 1
    assert scm.push.call_args[0][0] == repo.url
    assert scm.push.call_args[1] == {"push_target": "@", "force_push": False}


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job_with_scm_internal_error(
    active_mock: Callable,
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,  # pyright: ignore[reportUnusedParameter] Mock with side-effect
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision: Callable,
    make_landing_job: Callable,
    get_landing_worker: Callable,
    repo_type: str,
):
    repo = repo_mc(repo_type, force_push=True)
    scm = repo.scm

    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=[create_patch_revision(1)], **job_params)

    active_mock(scm, "push")
    scm.push.side_effect = [
        SCMInternalServerError("Some SCM error", "403"),
        scm.push.side_effect,
    ]

    worker = get_landing_worker(repo_type)

    assert not worker.run_job(job)
    assert job.status == JobStatus.DEFERRED, (
        "Job should have been deferred on first push exception."
    )
    assert "Some SCM error" in job.error

    assert worker.run_job(job)
    assert job.status == JobStatus.LANDED, "Job should have landed on second run."


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_no_diff_start_line(
    treestatusdouble,
    create_patch_revision,
    make_landing_job,
    caplog,
    get_landing_worker,
    repo_type: str,
):
    job_params = {
        "id": 1234,
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "attempts": 1,
    }
    job = make_landing_job(
        revisions=[create_patch_revision(1, patch=PATCH_WITHOUT_STARTLINE)],
        **job_params,
    )
    treestatusdouble.open_tree(job.target_repo.name)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.FAILED
    assert "Patch without a diff start line." in caplog.text


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_lose_push_race(
    monkeypatch,
    repo_mc,
    treestatusdouble,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    repo_type: str,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    job_params = {
        "id": 1234,
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(
        revisions=[create_patch_revision(1, patch=PATCH_PUSH_LOSER)], **job_params
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

    worker = get_landing_worker(repo_type)
    assert not worker.run_job(job)
    assert job.status == JobStatus.DEFERRED


@pytest.mark.parametrize(
    "repo_type, expected_error_log, patch",
    # Can't use itertools.product without similar overhead as this,
    # as we have more than one element in the first set.
    (
        scm + (patch,)
        for scm in (
            (SCMType.GIT, "Rejected hunk"),
            (SCMType.HG, "hunks FAILED"),
        )
        for patch in (
            PATCH_FORMATTED_2,
            PATCH_CHANGE_MISSING_CONTENT,
        )
    ),
)
@pytest.mark.django_db
def test_merge_conflict(
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,
    mock_phab_trigger_repo_update_apply_async: mock.Mock,
    create_patch_revision: Callable,
    make_landing_job: Callable,
    caplog: pytest.LogCaptureFixture,
    get_landing_worker: Callable,
    repo_type: str,
    expected_error_log: str,
    patch: str,
):
    repo = repo_mc(repo_type)
    treestatusdouble.open_tree(repo.name)

    job_params = {
        "id": 1234,
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(
        revisions=[
            create_patch_revision(1, patch=patch),
        ],
        **job_params,
    )

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.FAILED

    assert expected_error_log in caplog.text

    assert job.error_breakdown, "No error breakdown added to job"
    assert job.error_breakdown.get("rejects_paths"), (
        "Empty or missing reject information in error breakdown"
    )
    failed_paths = [p["path"] for p in job.error_breakdown["failed_paths"]]
    assert set(failed_paths) == set(job.error_breakdown["rejects_paths"].keys()), (
        "Mismatch between failed_paths and rejects_paths"
    )
    for fp in failed_paths:
        assert job.error_breakdown["rejects_paths"][fp].get("path"), (
            f"Empty or missing reject path for failed path {fp}"
        )
        assert job.error_breakdown["rejects_paths"][fp].get("content"), (
            f"Empty or missing reject content for failed path {fp}"
        )

    for fp in job.error_breakdown["failed_paths"]:
        if repo_type == SCMType.GIT:
            assert re.match(f"{repo.pull_path}/tree", fp["url"])
        else:  # SCMType.HG
            assert re.match(f"{repo.pull_path}/file", fp["url"])


@pytest.mark.parametrize(
    "repo_type,failing_check_commit_type",
    # We make a cross-product of all the SCM and all the bad actions.
    # As we don't want a cross-product of bad actions and reasons, we bundle them in a
    # tuple, that we deconstruct in the test.
    itertools.product(
        [SCMType.HG, SCMType.GIT],
        # All of FAILING_CHECK_TYPES, except for wpt
        [check_type for check_type in FAILING_CHECK_TYPES if check_type != "wpt"],
    ),
)
@pytest.mark.django_db
def test_failed_landing_job_checks(
    repo_mc,
    treestatusdouble,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    get_failing_check_diff,
    repo_type: str,
    failing_check_commit_type: str,
    get_failing_check_commit_reason: Callable,
    extract_email: Callable,
):
    """Ensure that checks fail non-compliant landings."""
    repo = repo_mc(repo_type, approval_required=True, autoformat_enabled=False)
    treestatusdouble.open_tree(repo.name)

    disallowed_revision, reason = get_failing_check_commit_reason(
        failing_check_commit_type
    )

    author_email = extract_email(disallowed_revision["author"])

    patch = (
        r"""# HG changeset patch
# User Test User <"""
        + author_email
        + """>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
"""
        + disallowed_revision["commitmsg"]
        + """
"""
        + get_failing_check_diff(failing_check_commit_type)
    )

    revisions = [create_patch_revision(1, patch=patch)]
    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": author_email,
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.FAILED
    assert reason in job.error


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_exception_landing_job_checks(
    treestatusdouble,
    monkeypatch: pytest.MonkeyPatch,
    create_patch_revision,
    make_landing_job,
    caplog,
    get_landing_worker,
    repo_type: str,
):
    job_params = {
        "id": 1234,
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "attempts": 1,
    }
    job = make_landing_job(
        revisions=[create_patch_revision(1)],
        **job_params,
    )
    treestatusdouble.open_tree(job.target_repo.name)

    exception_message = "Forcing exception when running checks"
    mock_landing_checks_run = mock.MagicMock()
    mock_landing_checks_run.side_effect = Exception(exception_message)
    monkeypatch.setattr(
        "lando.utils.landing_checks.LandingChecks.run", mock_landing_checks_run
    )

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.FAILED
    assert exception_message in caplog.text


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_failed_landing_job_notification(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
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
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.notify_user_of_landing_failure",
        mock_notify,
    )

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.FAILED
    assert mock_notify.call_count == 1


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_format_patch_success_unchanged(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    normal_patch,
    get_landing_worker,
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
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)

    new_commit_count = Commit.objects.filter(repo=repo).count()
    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_commit_count == len(revisions), (
        "Incorrect number of additional commits in the PushLog"
    )
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert job.status == JobStatus.LANDED, (
        "Successful landing should set `LANDED` status."
    )
    assert mock_phab_trigger_repo_update_apply_async.call_count == 1, (
        "Successful landing should trigger Phab repo update."
    )
    assert job.formatted_replacements is None, (
        "Autoformat making no changes should leave `formatted_replacements` empty."
    )
    assert job.autoformat_changes.count() == 0, (
        "Autoformat making no changes should record no `AutoformatChange` rows."
    )


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_format_single_success_changed(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
    repo_type: str,
):
    """Test formatting a single commit via amending."""
    repo = repo_mc(repo_type, autoformat_enabled=True)
    treestatusdouble.open_tree(repo.name)
    scm = repo.scm

    # Push the `mach` formatting patch.
    with scm.for_push("test@example.com"):
        ph = HgPatchHelper.from_string_io(io.StringIO(PATCH_FORMATTING_PATTERN_PASS))
        scm.apply_patch(
            ph.get_diff(),
            ph.get_commit_description(),
            ph.get_header("User"),
            ph.get_header("Date"),
        )
        scm.push(repo.push_path)
        pre_landing_tip = scm.describe_commit().hash

    # Upload a patch for formatting.
    job_params = {
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(
        revisions=[create_patch_revision(2, patch=PATCH_FORMATTED_1)], **job_params
    )

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job), "`run_job` should return `True` on a successful run."

    new_commit_count = Commit.objects.filter(repo=repo).count()
    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_commit_count == 1, (
        "Incorrect number of additional commits in the PushLog"
    )
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert job.status == JobStatus.LANDED, (
        "Successful landing should set `LANDED` status."
    )
    assert mock_phab_trigger_repo_update_apply_async.call_count == 1, (
        "Successful landing should trigger Phab repo update."
    )

    with scm.for_push(job.requester_email):
        # Get the commit message.
        desc = scm.describe_commit().desc.strip()

        # Get the content of the file after autoformatting.
        tip_content = scm.read_checkout_file("test.txt").encode("utf-8")

        # Get the hash behind the tip commit.
        parent_rev = scm.describe_commit().parents[0]
        hash_behind_current_tip = scm.describe_commit(parent_rev).hash

    assert tip_content == TESTTXT_FORMATTED_1, "`test.txt` is incorrect in base commit."

    assert desc == "bug 123: add another file for formatting 1", (
        "Autoformat via amend should not change commit message."
    )

    assert hash_behind_current_tip == pre_landing_tip, (
        "Autoformat via amending should only land a single commit."
    )

    if repo_type == SCMType.GIT:
        autoformat_change = job.autoformat_changes.get()
        assert autoformat_change.commit_sha == job.formatted_replacements[0], (
            "`AutoformatChange` should reference the amended commit SHA."
        )
        assert autoformat_change.changed_files == ["test.txt"], (
            "`AutoformatChange` should list the reformatted file."
        )
        assert autoformat_change.diff, (
            "`AutoformatChange` should record a non-empty diff."
        )
    else:
        assert job.autoformat_changes.count() == 0, (
            "Hg does not support capturing autoformat changes."
        )


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_format_stack_success_changed(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
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
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job), "`run_job` should return `True` on a successful run."

    new_commit_count = Commit.objects.filter(repo=repo).count()
    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_commit_count == len(revisions) + 1, (
        "Incorrect number of additional commits in the PushLog (should be one more than the number of revisions)"
    )
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert job.status == JobStatus.LANDED, (
        "Successful landing should set `LANDED` status."
    )
    assert mock_phab_trigger_repo_update_apply_async.call_count == 1, (
        "Successful landing should trigger Phab repo update."
    )

    with scm.for_push(job.requester_email):
        # Get the commit message.
        desc = scm.describe_commit().desc.strip()

        # Get the content of the file after autoformatting.
        rev3_content = scm.read_checkout_file("test.txt").encode("utf-8")

    assert rev3_content == TESTTXT_FORMATTED_2, (
        "`test.txt` is incorrect in base commit."
    )

    assert "# ignore-this-changeset" in desc, (
        "Commit message for autoformat commit should contain `# ignore-this-changeset`."
    )

    assert desc == AUTOFORMAT_COMMIT_MESSAGE.format(bugs="Bug 123"), (
        "Autoformat commit has incorrect commit message."
    )

    if repo_type == SCMType.GIT:
        autoformat_change = job.autoformat_changes.get()
        assert autoformat_change.commit_sha == job.formatted_replacements[0], (
            "`AutoformatChange` should reference the autoformat tip commit SHA."
        )
        assert autoformat_change.changed_files == ["test.txt"], (
            "`AutoformatChange` should list the reformatted file."
        )
        assert autoformat_change.diff, (
            "`AutoformatChange` should record a non-empty diff."
        )
    else:
        assert job.autoformat_changes.count() == 0, (
            "Hg does not support capturing autoformat changes."
        )


@pytest.mark.django_db
def test_run_mach_command_sets_mozbuild_state_path(tmp_path, git_landing_worker):
    """`run_mach_command` should export `MOZBUILD_STATE_PATH` from `extra_env`."""
    mozbuild_dir = tmp_path / "mozbuilds" / "test-repo"

    # `mach` echoes `$MOZBUILD_STATE_PATH` so we can verify it was exported.
    mach_file = tmp_path / "mach"
    mach_file.write_text('#!/bin/sh\necho "$MOZBUILD_STATE_PATH"\n')
    mach_file.chmod(0o755)

    output = git_landing_worker.run_mach_command(
        str(tmp_path), [], extra_env={"MOZBUILD_STATE_PATH": str(mozbuild_dir)}
    )

    assert output.strip() == str(mozbuild_dir), (
        "`MOZBUILD_STATE_PATH` should be set in the subprocess env."
    )
    assert mozbuild_dir.is_dir(), (
        "`run_mach_command` should create the `MOZBUILD_STATE_PATH` directory."
    )


@pytest.mark.django_db
def test_bootstrap_repos_runs_configured_command_sequence(repo_mc, git_landing_worker):
    commands = [
        ["artifact", "toolchain", "--from-build", "linux64-rust"],
        ["lint", "--setup", "-l", "eslint"],
    ]
    repo = repo_mc(
        SCMType.GIT,
        name="test-bootstrap-git",
        autoformat_enabled=True,
        autoformat_setup_commands=commands,
    )
    git_landing_worker.worker_instance.applicable_repos.set([repo])

    with mock.patch.object(
        git_landing_worker,
        "run_mach_command",
        side_effect=[subprocess.CalledProcessError(1, "mach"), "ok"],
    ) as run_mach:
        # `bootstrap_repos` should swallow the failure and keep going.
        git_landing_worker.bootstrap_repos()

    expected_env = {"MOZBUILD_STATE_PATH": repo.mozbuild_state_path}
    assert run_mach.call_args_list == [
        mock.call(repo.path, commands[0], extra_env=expected_env),
        mock.call(repo.path, commands[1], extra_env=expected_env),
    ], (
        "Each configured bootstrap command should run in order with the repo's state "
        "path, and a failing command should not abort the remaining commands."
    )


@pytest.mark.django_db
def test_bootstrap_repos_uses_artifact_default(repo_mc, git_landing_worker):
    """A repo without overrides bootstraps via the default `mach artifact` sequence."""
    repo = repo_mc(
        SCMType.GIT, name="test-bootstrap-default-git", autoformat_enabled=True
    )
    git_landing_worker.worker_instance.applicable_repos.set([repo])

    with mock.patch.object(git_landing_worker, "run_mach_command") as run_mach:
        git_landing_worker.bootstrap_repos()

    ran_commands = [call.args[1] for call in run_mach.call_args_list]
    assert ran_commands == repo.autoformat_setup_commands, (
        "Default bootstrap should run the artifact-toolchain sequence."
    )
    assert ["artifact", "toolchain", "--from-build", "linux64-rust"] in ran_commands, (
        "Default bootstrap should fetch the `rust` toolchain via `mach artifact`."
    )


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_format_patch_fail(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    create_patch_revision,
    make_landing_job,
    normal_patch,
    get_landing_worker,
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
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.notify_user_of_landing_failure",
        mock_notify,
    )

    worker = get_landing_worker(repo_type)
    assert not worker.run_job(job), (
        "`run_job` should return `False` when autoformatting fails."
    )

    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_push_count == 0, "The number of pushes shouldn't have changed"

    assert job.status == JobStatus.FAILED, (
        "Failed autoformatting should set `FAILED` job status."
    )
    assert "Lando failed to format your patch" in job.error, (
        "Error message is not set to show autoformat caused landing failure."
    )
    assert mock_notify.call_count == 1, (
        "User should be notified their landing was unsuccessful due to autoformat."
    )


@pytest.mark.parametrize(
    "repo_type",
    [
        SCMType.GIT,
        SCMType.HG,
    ],
)
@pytest.mark.django_db
def test_format_patch_no_landoini(
    repo_mc,
    treestatusdouble,
    monkeypatch,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    get_landing_worker,
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
        "status": JobStatus.IN_PROGRESS,
        "requester_email": "test@example.com",
        "target_repo": repo,
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.landing_worker.notify_user_of_landing_failure",
        mock_notify,
    )

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.LANDED, (
        "Missing `.lando.ini` should not inhibit landing."
    )
    assert mock_notify.call_count == 0, (
        "Should not notify user of landing failure due to `.lando.ini` missing."
    )
    assert mock_phab_trigger_repo_update_apply_async.call_count == 1, (
        "Successful landing should trigger Phab repo update."
    )


@pytest.mark.django_db
def test_landing_job_revisions_sorting(
    create_patch_revision,
    make_landing_job,
):
    revisions = [
        create_patch_revision(1),
        create_patch_revision(2),
        create_patch_revision(3),
    ]
    job_params = {
        "status": JobStatus.SUBMITTED,
        "requester_email": "test@example.com",
        "attempts": 1,
    }
    job = make_landing_job(revisions=revisions, **job_params)

    assert list(job.revisions.all()) == revisions
    new_ordering = [revisions[2], revisions[0], revisions[1]]
    job.sort_revisions(new_ordering)
    job.save()
    job = LandingJob.objects.get(id=job.id)
    assert list(job.revisions.all()) == new_ordering


@pytest.mark.parametrize(
    "scm_type,repo_name",
    [
        (SCMType.HG, "mozilla-central"),
        (SCMType.GIT, "firefox"),
    ],
)
@pytest.mark.django_db
def test_worker_active_repos_updated_when_tree_closed(
    scm_type,
    repo_name,
    treestatusdouble,
    monkeypatch,
    get_landing_worker,
):
    repo = Repo.objects.get(name=repo_name)
    treestatusdouble.open_tree(repo.name)

    worker = get_landing_worker(scm_type)
    worker.refresh_active_repos()
    assert repo in worker.active_repos, (
        f"The {scm_type} repo should be active when its tree is open."
    )
    assert repo in worker.enabled_repos, (
        f"The {scm_type} repo should be enabled when its tree is open."
    )

    treestatusdouble.close_tree(repo.name)
    worker.refresh_active_repos()
    assert repo not in worker.active_repos, (
        f"The {scm_type} repo should not be active when its tree is closed."
    )
    assert repo in worker.enabled_repos, (
        f"The {scm_type} repo should still be enabled when its tree is closed."
    )


def setup_three_way_repo(
    git_repo: Path, apply_patch: Callable, base_diff: str, tip_diff: str
) -> str:
    """Seed `git_repo` with a multi-line base commit and a tip commit.

    The tip commit applies `tip_diff`. Returns the base commit SHA the patch is
    authored against.
    """
    scm = GitSCM(str(git_repo))
    apply_patch(scm, base_diff, "Base content for 3-way test")
    base_sha = scm.head_ref()
    apply_patch(scm, tip_diff, "Change a line on the tip")
    return base_sha


@pytest.mark.parametrize(
    "provide_base, expected_status",
    [
        # With the base available, the worker reconstructs and rebases, so the
        # context shift is recovered and the landing succeeds.
        pytest.param(True, JobStatus.LANDED, id="with-base-recovers"),
        # Without it, the worker applies at the tip with a 2-way apply, which the
        # context shift defeats.
        pytest.param(False, JobStatus.FAILED, id="without-base-fails"),
    ],
)
@pytest.mark.django_db
def test_three_way_landing_handles_context_shift(
    provide_base: bool,
    expected_status: str,
    repo_mc: Callable,
    git_repo: Path,
    treestatusdouble: TreeStatusDouble,
    mock_phab_trigger_repo_update_apply_async: mock.Mock,
    create_patch_revision: Callable,
    make_landing_job: Callable,
    get_landing_worker: Callable,
    apply_patch: Callable,
    three_way_base_diff: str,
    three_way_context_shift_diff: str,
    three_way_patch: str,
):
    """A recorded base lets the worker recover a context shift that 2-way rejects."""
    base_sha = setup_three_way_repo(
        git_repo, apply_patch, three_way_base_diff, three_way_context_shift_diff
    )

    repo = repo_mc(SCMType.GIT)
    treestatusdouble.open_tree(repo.name)

    revision = create_patch_revision(1, patch=three_way_patch)
    if provide_base:
        revision.base_revision = base_sha
        revision.save()

    job = make_landing_job(
        revisions=[revision],
        status=JobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        target_repo=repo,
        attempts=1,
    )

    worker = get_landing_worker(SCMType.GIT)
    assert worker.run_job(job), "`run_job` returns `True` in both permanent states."
    assert job.status == expected_status, (
        "Base availability should determine whether the context shift lands."
    )

    if expected_status != JobStatus.LANDED:
        return

    # The worker's checkout reflects the landed tip, with both changes 3-way merged.
    landed = repo.scm.read_checkout_file("test.txt")
    assert "line6 changed on tip" in landed, "Tip's change should be preserved."
    assert "line8 modified by patch" in landed, "Patch's change should be applied."

    revision.refresh_from_db()
    assert revision.commit_id, "The post-rebase commit hash should be recorded."


@pytest.mark.django_db
def test_three_way_landing_conflict_reports_breakdown(
    repo_mc: Callable,
    git_repo: Path,
    treestatusdouble: TreeStatusDouble,
    mock_phab_trigger_repo_update_apply_async: mock.Mock,
    create_patch_revision: Callable,
    make_landing_job: Callable,
    get_landing_worker: Callable,
    apply_patch: Callable,
    three_way_base_diff: str,
    three_way_conflicting_diff: str,
    three_way_patch: str,
):
    """A genuine 3-way conflict fails with a populated `error_breakdown`."""
    base_sha = setup_three_way_repo(
        git_repo, apply_patch, three_way_base_diff, three_way_conflicting_diff
    )

    repo = repo_mc(SCMType.GIT)
    treestatusdouble.open_tree(repo.name)

    revision = create_patch_revision(1, patch=three_way_patch)
    revision.base_revision = base_sha
    revision.save()

    job = make_landing_job(
        revisions=[revision],
        status=JobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        target_repo=repo,
        attempts=1,
    )

    worker = get_landing_worker(SCMType.GIT)
    assert worker.run_job(job), "`run_job` returns `True` after a permanent failure."
    assert job.status == JobStatus.FAILED, "A true 3-way conflict should fail the job."

    assert "test.txt" in job.error, "The job error should name the conflicting file."
    assert "conflict" in job.error.lower(), (
        "The job error should indicate a merge conflict."
    )

    assert job.error_breakdown, "A conflict should produce an error breakdown."
    rejects_paths = job.error_breakdown.get("rejects_paths")
    assert rejects_paths, "The breakdown should record the conflicting paths."
    assert "test.txt" in rejects_paths, "The conflicting file should be listed."
    assert rejects_paths["test.txt"].get("content"), (
        "The breakdown should include the conflict content for display."
    )

    failed_paths = [path["path"] for path in job.error_breakdown["failed_paths"]]
    assert set(failed_paths) == set(rejects_paths.keys()), (
        "`failed_paths` and `rejects_paths` should be consistent."
    )
