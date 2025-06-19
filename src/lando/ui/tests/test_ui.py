import pytest

from lando.main.models.landing_job import JobStatus, LandingJob
from lando.main.scm.consts import SCM_TYPE_GIT


@pytest.mark.django_db
def test_landing_queue_view(client, repo_mc):
    # Create a job and actions
    repo = repo_mc(SCM_TYPE_GIT)
    jobs = [
        LandingJob.objects.create(target_repo=repo, status=JobStatus.SUBMITTED)
        for _ in range(3)
    ]

    job = jobs[0]

    # Fetch job status.
    response = client.get(
        f"/landings/{job.id}/",
    )

    assert response.status_code == 200, "Job view should render correctly"
    assert response.json() == {"details": "Token api-bad-key was not found."}


@pytest.mark.skipped
@pytest.mark.django_db
def test_landing_revision_redirect(client, repo_mc):
    pass
