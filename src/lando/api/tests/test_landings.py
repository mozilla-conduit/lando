import io
import itertools
import re
import unittest.mock as mock
from typing import Callable

import pytest

from lando.api.legacy.workers.landing_worker import (
    AUTOFORMAT_COMMIT_MESSAGE,
)
from lando.api.tests.mocks import TreeStatusDouble
from lando.conftest import FAILING_CHECK_TYPES
from lando.main.models import (
    JobStatus,
    LandingJob,
    Repo,
    RevisionLandingJob,
)
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.scm.exceptions import SCMInternalServerError
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
        (SCM_TYPE_GIT, [(1, {"patch": PATCH_BINARY_GITATTRIBUTES})]),
        (SCM_TYPE_GIT, [(1, {"patch": BINARY_PATCH})]),
        # Hg
        (
            SCM_TYPE_HG,
            [
                (1, {"patch": None}),
                (2, {"patch": None}),
            ],
        ),
        (SCM_TYPE_HG, [(1, {"patch": LARGE_PATCH})]),
        (SCM_TYPE_HG, [(1, {"patch": PATCH_BINARY_GITATTRIBUTES})]),
        (SCM_TYPE_HG, [(1, {"patch": BINARY_PATCH})]),
    ],
)
@pytest.mark.django_db
def test_integrated_execute_job(
    repo_mc,
    treestatusdouble,
    mock_phab_trigger_repo_update_apply_async,
    create_patch_revision,
    make_landing_job,
    repo_type: str,
    revisions_params,
    get_landing_worker,
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
    assert (
        mock_phab_trigger_repo_update_apply_async.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    # The diff_id is not set for landings not created from Phabricator transplants.
    assert job.landed_revisions == {
        r.id: None for r in revisions
    }, "Incorrect mapping of internal revision IDs to diff ID"

    new_commit_count = Commit.objects.filter(repo=repo).count()
    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_commit_count == len(
        revisions
    ), "Incorrect number of additional commits in the PushLog"
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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
        assert (
            revision_job.commit_id
        ), "`commit_id` should be set on `RevisionLandingJob` object."


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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
    assert (
        revision_jobs[0].commit_id is None
    ), "`commit_id` should not be set for un-landed job."


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
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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
    assert (
        job.status == JobStatus.DEFERRED
    ), "Job should have been deferred on first push exception."
    assert "Some SCM error" in job.error

    assert worker.run_job(job)
    assert job.status == JobStatus.LANDED, "Job should have landed on second run."


@pytest.mark.parametrize(
    "repo_type",
    [
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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
            (SCM_TYPE_GIT, "Rejected hunk"),
            (SCM_TYPE_HG, "hunks FAILED"),
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

    for fp in job.error_breakdown["failed_paths"]:
        if repo_type == SCM_TYPE_GIT:
            assert re.match(f"{repo.pull_path}/tree", fp["url"])
        else:  # SCM_TYPE_HG
            assert re.match(f"{repo.pull_path}/file", fp["url"])


@pytest.mark.parametrize(
    "repo_type,failing_check_commit_type",
    # We make a cross-product of all the SCM and all the bad actions.
    # As we don't want a cross-product of bad actions and reasons, we bundle them in a
    # tuple, that we deconstruct in the test.
    itertools.product(
        [SCM_TYPE_HG, SCM_TYPE_GIT],
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
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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

    scm = job.target_repo.scm

    exception_message = "Forcing exception when running checks"
    mock_update_repo = mock.MagicMock()
    mock_update_repo.side_effect = Exception(exception_message)
    monkeypatch.setattr(scm, "get_patch_helper", mock_update_repo)

    worker = get_landing_worker(repo_type)
    assert worker.run_job(job)
    assert job.status == JobStatus.FAILED
    assert exception_message in caplog.text


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
        SCM_TYPE_GIT,
        SCM_TYPE_HG,
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
    assert new_commit_count == len(
        revisions
    ), "Incorrect number of additional commits in the PushLog"
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert (
        job.status == JobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_phab_trigger_repo_update_apply_async.call_count == 1
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
    assert (
        new_commit_count == 1
    ), "Incorrect number of additional commits in the PushLog"
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert (
        job.status == JobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_phab_trigger_repo_update_apply_async.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with scm.for_push(job.requester_email):
        # Get the commit message.
        desc = scm.describe_commit().desc.strip()

        # Get the content of the file after autoformatting.
        tip_content = scm.read_checkout_file("test.txt").encode("utf-8")

        # Get the hash behind the tip commit.
        parent_rev = scm.describe_commit().parents[0]
        hash_behind_current_tip = scm.describe_commit(parent_rev).hash

    assert tip_content == TESTTXT_FORMATTED_1, "`test.txt` is incorrect in base commit."

    assert (
        desc == "bug 123: add another file for formatting 1"
    ), "Autoformat via amend should not change commit message."

    assert (
        hash_behind_current_tip == pre_landing_tip
    ), "Autoformat via amending should only land a single commit."


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
    assert (
        new_commit_count == len(revisions) + 1
    ), "Incorrect number of additional commits in the PushLog (should be one more than the number of revisions)"
    assert new_push_count == 1, "Incorrect number of additional pushes in the PushLog"

    assert (
        job.status == JobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_phab_trigger_repo_update_apply_async.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with scm.for_push(job.requester_email):
        # Get the commit message.
        desc = scm.describe_commit().desc.strip()

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
    assert not worker.run_job(
        job
    ), "`run_job` should return `False` when autoformatting fails."

    new_push_count = Push.objects.filter(repo=repo).count()
    assert new_push_count == 0, "The number of pushes shouldn't have changed"

    assert (
        job.status == JobStatus.FAILED
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
    assert (
        job.status == JobStatus.LANDED
    ), "Missing `.lando.ini` should not inhibit landing."
    assert (
        mock_notify.call_count == 0
    ), "Should not notify user of landing failure due to `.lando.ini` missing."
    assert (
        mock_phab_trigger_repo_update_apply_async.call_count == 1
    ), "Successful landing should trigger Phab repo update."


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


@pytest.mark.django_db
def test_worker_active_repos_updated_when_tree_closed(
    treestatusdouble,
    monkeypatch,
    get_landing_worker,
):
    repo = Repo.objects.get(name="mozilla-central")
    treestatusdouble.open_tree(repo.name)

    worker = get_landing_worker(SCM_TYPE_HG)
    worker.refresh_active_repos()
    assert repo in worker.active_repos
    assert repo in worker.enabled_repos

    treestatusdouble.close_tree(repo.name)
    worker.refresh_active_repos()
    assert repo not in worker.active_repos
    assert repo in worker.enabled_repos
