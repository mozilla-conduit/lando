import json

import pytest

from lando.main.models import LandingJob, LandingJobStatus, Repo
from lando.main.scm import SCM_TYPE_HG


@pytest.fixture
def landing_job(db):
    def _landing_job(status, requester_email="tuser@example.com"):
        job = LandingJob(
            status=status,
            revision_to_diff_id={},
            revision_order=[],
            requester_email=requester_email,
            repository_name="",
        )
        job.save()
        return job

    return _landing_job


def test_cancel_landing_job_cancels_when_submitted(
    db, authenticated_client, user, landing_job, mock_permissions
):
    """Test happy path; cancelling a job that has not started yet."""
    job = landing_job(LandingJobStatus.SUBMITTED, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": LandingJobStatus.CANCELLED.value}),
    )

    assert response.status_code == 200
    assert response.json()["id"] == job.id
    job.refresh_from_db()
    assert job.status == LandingJobStatus.CANCELLED


def test_cancel_landing_job_cancels_when_deferred(
    db, authenticated_client, user, landing_job, mock_permissions
):
    """Test happy path; cancelling a job that has been deferred."""
    job = landing_job(LandingJobStatus.DEFERRED, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": LandingJobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 200
    assert response.json()["id"] == job.id
    job.refresh_from_db()
    assert job.status == LandingJobStatus.CANCELLED


def test_cancel_landing_job_fails_in_progress(
    db, authenticated_client, user, landing_job, mock_permissions
):
    """Test trying to cancel a job that is in progress fails."""
    job = landing_job(LandingJobStatus.IN_PROGRESS, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": LandingJobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 400
    assert (
        "Landing job status (IN_PROGRESS) does not allow cancelling."
        in response.json()["errors"]
    )
    job.refresh_from_db()
    assert job.status == LandingJobStatus.IN_PROGRESS


def test_cancel_landing_job_fails_not_owner(
    db, authenticated_client, landing_job, mock_permissions
):
    """Test trying to cancel a job that is created by a different user."""
    job = landing_job(LandingJobStatus.SUBMITTED, "anotheruser@example.org")
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": LandingJobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        f"User not authorized to update landing job {job.id}"
    )

    job.refresh_from_db()
    assert job.status == LandingJobStatus.SUBMITTED


def test_cancel_landing_job_fails_not_found(
    db, authenticated_client, landing_job, mock_permissions
):
    """Test trying to cancel a job that does not exist."""
    response = authenticated_client.put(
        "/landing_jobs/1/",
        json.dumps({"status": LandingJobStatus.CANCELLED.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ("A landing job with ID 1 was not found.")


def test_cancel_landing_job_fails_bad_input(
    db, authenticated_client, user, landing_job, mock_permissions
):
    """Test trying to send an invalid status to the update endpoint."""
    job = landing_job(LandingJobStatus.SUBMITTED, requester_email=user.email)
    response = authenticated_client.put(
        f"/landing_jobs/{job.id}/",
        json.dumps({"status": LandingJobStatus.IN_PROGRESS.value}),
        permissions=mock_permissions,
    )

    assert response.status_code == 400
    assert (
        "The provided status IN_PROGRESS is not allowed." in response.json()["errors"]
    )
    job.refresh_from_db()
    assert job.status == LandingJobStatus.SUBMITTED


def test_landing_job_acquire_job_job_queue_query(db, mocked_repo_config):
    REPO = Repo.objects.create(name="test-repo", scm_type=SCM_TYPE_HG)
    jobs = [
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            target_repo=REPO,
            revision_to_diff_id={"1": 1},
            revision_order=["1"],
        ),
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            target_repo=REPO,
            revision_to_diff_id={"2": 2},
            revision_order=["2"],
        ),
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
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
    jobs[2].status = LandingJobStatus.IN_PROGRESS
    jobs[1].status = LandingJobStatus.CANCELLED

    for job in jobs:
        job.save()
    # The now IN_PROGRESS job should be first, and the cancelled job should
    # not appear in the queue.
    queue_items = LandingJob.job_queue_query(repositories=[REPO], grace_seconds=0).all()
    assert len(queue_items) == 2
    assert queue_items[0].id == jobs[2].id
    assert queue_items[1].id == jobs[0].id
    assert jobs[1] not in queue_items
