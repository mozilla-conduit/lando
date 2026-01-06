import json

import pytest

from lando.main.models import JobStatus, LandingJob, Repo
from lando.main.scm import SCMType


@pytest.fixture
def landing_job(repo_mc):
    def _landing_job(status, requester_email="tuser@example.com"):
        job = LandingJob(
            status=status,
            revision_to_diff_id={},
            revision_order=[],
            requester_email=requester_email,
            target_repo=repo_mc(scm_type=SCMType.GIT),
        )
        job.save()
        return job

    return _landing_job


@pytest.mark.django_db
def test_cancel_landing_job_cancels_when_submitted(
    authenticated_client, user, landing_job, mock_permissions
):
    """Test happy path; cancelling a job that has not started yet."""
    job = landing_job(JobStatus.SUBMITTED, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": JobStatus.CANCELLED.value}),
    )

    assert response.status_code == 200
    assert response.json()["id"] == job.id
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED


@pytest.mark.django_db
def test_cancel_landing_job_cancels_when_deferred(
    authenticated_client, user, landing_job, mock_permissions
):
    """Test happy path; cancelling a job that has been deferred."""
    job = landing_job(JobStatus.DEFERRED, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": JobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.json()["id"] == job.id
    job.refresh_from_db()
    assert job.status == JobStatus.CANCELLED


@pytest.mark.django_db
def test_cancel_landing_job_fails_in_progress(
    authenticated_client, user, landing_job, mock_permissions
):
    """Test trying to cancel a job that is in progress fails."""
    job = landing_job(JobStatus.IN_PROGRESS, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": JobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 400
    assert (
        "Landing job status (IN_PROGRESS) does not allow cancelling."
        in response.json()["errors"]
    )
    job.refresh_from_db()
    assert job.status == JobStatus.IN_PROGRESS


@pytest.mark.django_db
def test_cancel_landing_job_fails_not_owner(
    authenticated_client, landing_job, mock_permissions
):
    """Test trying to cancel a job that is created by a different user."""
    job = landing_job(JobStatus.SUBMITTED, "anotheruser@example.org")
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": JobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        f"User not authorized to update landing job {job.id}"
    )

    job.refresh_from_db()
    assert job.status == JobStatus.SUBMITTED


@pytest.mark.django_db
def test_cancel_landing_job_fails_not_found(
    authenticated_client, landing_job, mock_permissions
):
    """Test trying to cancel a job that does not exist."""
    response = authenticated_client.put(
        "/landing_jobs/1/",
        json.dumps({"status": JobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ("A landing job with ID 1 was not found.")


@pytest.mark.django_db
def test_cancel_landing_job_fails_bad_input(
    authenticated_client, user, landing_job, mock_permissions
):
    """Test trying to send an invalid status to the update endpoint."""
    job = landing_job(JobStatus.SUBMITTED, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": JobStatus.IN_PROGRESS.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 400
    assert (
        "The provided status IN_PROGRESS is not allowed." in response.json()["errors"]
    )
    job.refresh_from_db()
    assert job.status == JobStatus.SUBMITTED


@pytest.mark.django_db
def test_landing_job_acquire_job_job_queue_query(mocked_repo_config):
    REPO = Repo.objects.create(name="test-repo", scm_type=SCMType.GIT)
    jobs = [
        LandingJob(
            status=JobStatus.SUBMITTED,
            requester_email="test@example.com",
            target_repo=REPO,
            revision_to_diff_id={"1": 1},
            revision_order=["1"],
        ),
        LandingJob(
            status=JobStatus.SUBMITTED,
            requester_email="test@example.com",
            target_repo=REPO,
            revision_to_diff_id={"2": 2},
            revision_order=["2"],
        ),
        LandingJob(
            status=JobStatus.SUBMITTED,
            requester_email="test@example.com",
            target_repo=REPO,
            revision_to_diff_id={"3": 3},
            revision_order=["3"],
        ),
    ]
    for job in jobs:
        job.save()
    # Queue order should match the order the jobs were created in.

    for qjob, job in zip(
        LandingJob.job_queue_query(repositories=[REPO]), jobs, strict=False
    ):
        assert qjob.id == job.id

    # Update the last job to be in progress and mark the middle job to be
    # cancelled so that the queue changes.
    jobs[2].status = JobStatus.IN_PROGRESS
    jobs[1].status = JobStatus.CANCELLED

    for job in jobs:
        job.save()
    # The now IN_PROGRESS job should be first, and the cancelled job should
    # not appear in the queue.
    queue_items = LandingJob.job_queue_query(repositories=[REPO], grace_seconds=0).all()
    assert len(queue_items) == 2
    assert queue_items[0].id == jobs[2].id
    assert queue_items[1].id == jobs[0].id
    assert jobs[1] not in queue_items
