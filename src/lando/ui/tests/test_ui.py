import re

import pytest

from lando import test_settings as settings
from lando.main import scm
from lando.main.models.landing_job import JobStatus, LandingJob
from lando.main.scm.consts import SCM_TYPE_GIT


@pytest.mark.django_db
def test_queued_landing_job_view(
    client, repo_mc, treestatusdouble, landing_worker_instance, make_landing_job
):
    repo = repo_mc(SCM_TYPE_GIT)
    treestatusdouble.close_tree(repo.name)

    # We need a landing worker to exist so the queue can be built, but we don't use it
    # directly in the test.
    landing_worker_instance(scm.SCM_TYPE_GIT)

    jobs = [
        make_landing_job(target_repo=repo, status=JobStatus.SUBMITTED) for _ in range(3)
    ]

    def get_job_view(job: LandingJob) -> str:
        phab_id = f"D{job.revisions[0].revision_id}"
        response = client.get(
            f"/{phab_id}/landings/{job.id}/",
        )
        assert response.status_code == 200, "Job view should render correctly"
        page_html = response.text

        assert f"Landing Job {job.id}" in page_html, "Missing title in job view"
        assert (
            f"{settings.PHABRICATOR_URL}/{phab_id}" in page_html
        ), "Missing Phabricator information in job view"
        assert re.search(
            f"Tree Status for.*{repo.name}.*closed", page_html
        ), "Missing TreeStatus information in job view"

        return page_html

    page_html = get_job_view(jobs[0])
    assert "ahead in the queue" not in page_html, "Unexpected queue state in job view"

    page_html = get_job_view(jobs[1])
    assert (
        "There is 1 job ahead in the queue" in page_html
    ), "Unexpected queue state in job view"
    page_html = get_job_view(jobs[2])
    assert (
        "There are 2 jobs ahead in the queue" in page_html
    ), "Unexpected queue state in job view"


@pytest.mark.django_db
def test_landing_revision_redirect(client, repo_mc, make_landing_job):
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
