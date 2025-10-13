import itertools
import re
from typing import Callable

import pytest
from django.test import Client

from lando import test_settings as settings
from lando.api.tests.mocks import TreeStatusDouble
from lando.main import scm
from lando.main.models import JobStatus, LandingJob
from lando.main.models.commit_map import CommitMap
from lando.main.scm import SCM_TYPE_GIT


@pytest.mark.django_db
def test_queued_landing_job_view(
    client: Client,
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,
    landing_worker_instance: Callable,
    make_landing_job: Callable,
):
    repo = repo_mc(SCM_TYPE_GIT)
    treestatusdouble.close_tree(repo.name)

    # We need a landing worker to exist so the queue can be built, but we don't use it
    # directly in the test.
    landing_worker_instance(scm.SCM_TYPE_GIT)

    jobs = [
        make_landing_job(target_repo=repo, status=JobStatus.SUBMITTED) for _ in range(3)
    ]

    page_html = _fetch_job_view(client, jobs[0])
    assert "ahead in the queue" not in page_html, "Unexpected queue state in job view"
    assert re.search(
        f"Tree Status for.*{repo.name}.*closed", page_html
    ), "Missing TreeStatus information in job view"

    page_html = _fetch_job_view(client, jobs[1])
    assert (
        "There is 1 job ahead in the queue" in page_html
    ), "Unexpected queue state in job view"
    page_html = _fetch_job_view(client, jobs[2])
    assert (
        "There are 2 jobs ahead in the queue" in page_html
    ), "Unexpected queue state in job view"


@pytest.mark.django_db
def test_landed_landing_job_view(
    client: Client,
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,
    landing_worker_instance: Callable,
    make_landing_job: Callable,
    commit_maps: list[CommitMap],
):
    cmap = commit_maps[0]

    # This test assumes that the URL of the repo_mc matches commit_maps[].git_repo_name.
    repo = repo_mc(SCM_TYPE_GIT)
    treestatusdouble.close_tree(repo.name)

    # We need a landing worker to exist so the queue can be built, but we don't use it
    # directly in the test.
    landing_worker_instance(scm.SCM_TYPE_GIT)

    job = make_landing_job(
        target_repo=repo, status=JobStatus.LANDED, landed_commit_id=cmap.git_hash
    )

    page_html = _fetch_job_view(client, job)
    assert (
        "ahead in the queue" not in page_html
    ), "Unexpected queue state in landed job view"
    assert f"{settings.TREEHERDER_URL}/jobs?revision={cmap.hg_hash}" in page_html


@pytest.mark.parametrize(
    "error,error_breakdown",
    itertools.product(
        (
            (
                'Problem while applying patch in revision 264890:\n\nChecking patch browser/components/preferences/widgets/setting-group/setting-group.mjs...\nHunk #1 succeeded at 43 (offset 16 lines).\nHunk #2 succeeded at 114 (offset 19 lines).\nChecking patch browser/components/preferences/widgets/setting-control/setting-control.mjs...\nHunk #1 succeeded at 178 (offset -10 lines).\nerror: while searching for:\n      }\n      this.#lastSetting = this.setting;\n      this.setValue();\n      this.setting.on("change", this.onSettingChange);\n    }\n    this.hidden = !this.setting.visible;\n  }\n\n  updated() {\n    this.controlRef?.value?.requestUpdate();\n  }\n\n  /**\n\nerror: patch failed: browser/components/preferences/widgets/setting-control/setting-control.mjs:209\nChecking patch browser/components/preferences/tests/chrome/test_setting_group.html...\nChecking patch browser/components/preferences/main.js...\nHunk #1 succeeded at 404 (offset 185 lines).\nApplied patch browser/components/preferences/widgets/setting-group/setting-group.mjs cleanly.\nApplying patch browser/components/preferences/widgets/setting-control/setting-control.mjs with 1 reject...\nHunk #1 applied cleanly.\nRejected hunk #2.\nApplied patch browser/components/preferences/tests/chrome/test_setting_group.html cleanly.\nApplied patch browser/components/preferences/main.js cleanly.\n',
            )
        ),
        (
            None,
            {
                "revision_id": 264890,
                "failed_paths": [
                    {
                        "url": "https://github.com/mozilla-firefox/firefox/tree/9d7faf035e9590310b3f6c86171a06aa30c29132/browser/components/preferences/widgets/setting-control/setting-control.mjs",
                        "path": "browser/components/preferences/widgets/setting-control/setting-control.mjs",
                        "changeset_id": "9d7faf035e9590310b3f6c86171a06aa30c29132",
                    }
                ],
                "rejects_paths": {
                    "browser/components/preferences/widgets/setting-control/setting-control.mjs": {
                        "path": "browser/components/preferences/widgets/setting-control/setting-control.mjs.rej",
                        "content": 'diff a/browser/components/preferences/widgets/setting-control/setting-control.mjs b/browser/components/preferences/widgets/setting-control/setting-control.mjs\t(rejected hunks)\n@@ -209,13 +209,20 @@\n       }\n       this.#lastSetting = this.setting;\n       this.setValue();\n       this.setting.on("change", this.onSettingChange);\n     }\n+    let prevHidden = this.hidden;\n     this.hidden = !this.setting.visible;\n+    if (prevHidden != this.hidden) {\n+      this.dispatchEvent(new Event("visibility-change", { bubbles: true }));\n+    }\n   }\n \n+  /**\n+   * @type {MozLitElement[\'updated\']}\n+   */\n   updated() {\n     this.controlRef?.value?.requestUpdate();\n   }\n \n   /**\n',
                    }
                },
            },
            {
                "revision_id": 264890,
                "failed_paths": [
                    {
                        "url": "https://github.com/mozilla-firefox/firefox/tree/9d7faf035e9590310b3f6c86171a06aa30c29132/browser/components/preferences/widgets/setting-control/setting-control.mjs",
                        "path": "browser/components/preferences/widgets/setting-control/setting-control.mjs",
                        "changeset_id": "9d7faf035e9590310b3f6c86171a06aa30c29132",
                    }
                ],
                "rejects_paths": {
                    "browser/components/preferences/widgets/setting-control/setting-control.mjs": {
                        "path": "browser/components/preferences/widgets/setting-control/setting-control.mjs.rej",
                        # content removed
                    }
                },
            },
        ),
    ),
)
@pytest.mark.django_db
def test_error_landing_job_view(
    client: Client,
    repo_mc: Callable,
    treestatusdouble: TreeStatusDouble,
    make_landing_job: Callable,
    error: str,
    error_breakdown: str,
):
    repo = repo_mc(SCM_TYPE_GIT)
    treestatusdouble.close_tree(repo.name)

    job = make_landing_job(
        target_repo=repo,
        status=JobStatus.FAILED,
        error=error,
        error_breakdown=error_breakdown,
    )

    page_html = _fetch_job_view(client, job)
    if error_breakdown:
        # When present, the raw error is hidden behind a button.
        assert "Show raw error output" in page_html
        path = (
            "browser/components/preferences/widgets/setting-control/setting-control.mjs"
        )
        if "content" not in error_breakdown["rejects_paths"][path]:
            assert f"Error parsing error for {path}." in page_html
    else:
        assert "Raw error output" in page_html

    assert (
        f"try rebasing your changes on the latest commits from {job.target_repo.short_name}"
        in page_html
    )


def _fetch_job_view(client, job: LandingJob) -> str:
    phab_id = f"D{job.revisions[0].revision_id}"
    response = client.get(
        f"/{phab_id}/landings/{job.id}/",
    )
    assert response.status_code == 200, "Job view should return an OK status code"
    page_html = response.text

    assert f"Landing Job {job.id}" in page_html, "Missing title in job view"
    assert (
        f"{settings.PHABRICATOR_URL}/{phab_id}" in page_html
    ), "Missing Phabricator information in job view"

    return page_html


@pytest.mark.django_db
def test_landing_revision_redirect(
    client: Client,
    repo_mc: Callable,
    make_landing_job: Callable,
):
    # Create a job and actions
    repo = repo_mc(SCM_TYPE_GIT)
    jobs = [make_landing_job(target_repo=repo, status=JobStatus.SUBMITTED)]

    job = jobs[0]

    # Fetch job status.
    response = client.get(
        f"/landings/{job.id}/",
    )

    assert response.status_code == 302, "Landing job view should redirect"
    assert (
        response.url == f"/D{job.revisions[0].revision_id}/landings/{job.id}/"
    ), "Landing job view should redirect to revision URL"
