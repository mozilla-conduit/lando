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
