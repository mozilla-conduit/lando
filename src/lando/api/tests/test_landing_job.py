import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from lando.main.models import JobAction, JobStatus, LandingJob, Repo
from lando.main.scm import SCM_TYPE_GIT


@pytest.fixture
def landing_job(repo_mc):
    def _landing_job(status, requester_email="tuser@example.com"):
        job = LandingJob(
            status=status,
            revision_to_diff_id={},
            revision_order=[],
            requester_email=requester_email,
            target_repo=repo_mc(scm_type=SCM_TYPE_GIT),
        )
        job.save()
        return job

    return _landing_job


@pytest.mark.django_db
def test_cancel_landing_job_cancels_when_submitted(
    authenticated_client, user, landing_job
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
    REPO = Repo.objects.create(name="test-repo", scm_type=SCM_TYPE_GIT)
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


@pytest.mark.django_db
def test_processing_no_timing_metrics_for_deferred_status(landing_job):
    """Timing metrics are NOT sent when job is deferred."""
    job = landing_job(JobStatus.SUBMITTED)

    with mock.patch("lando.main.models.jobs.statsd") as mock_statsd:
        with job.processing():
            job.status = JobStatus.DEFERRED

        # But timing metrics should NOT be sent for deferred jobs
        mock_statsd.timer.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "final_status",
    [
        JobStatus.LANDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ],
)
def test_processing_sends_timing_for_all_final_statuses(landing_job, final_status):
    """Timing metrics are sent for all final job statuses."""
    job = landing_job(JobStatus.SUBMITTED)
    job.created_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    job.save()

    with mock.patch("lando.main.models.jobs.statsd") as mock_statsd:
        with job.processing():
            job.status = final_status

        # Verify timing metrics were sent
        assert mock_statsd.timer.call_count == 2

        repo_name = job.target_repo.name
        mock_statsd.timer.assert_any_call(
            f"lando-api.job.{repo_name}.Landing.pending_time", mock.ANY
        )
        mock_statsd.timer.assert_any_call(
            f"lando-api.job.{repo_name}.Landing.processing_time", mock.ANY
        )


@pytest.mark.django_db
def test_processing_calculates_pending_time_correctly(landing_job):
    """Pending time is calculated from job creation to processing start."""
    job = landing_job(JobStatus.SUBMITTED)

    # Set created_at to 30 seconds ago
    created_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    job.created_at = created_time
    job.save()

    with mock.patch("lando.main.models.jobs.statsd") as mock_statsd:
        with job.processing():
            job.status = JobStatus.LANDED

        # Get the timedelta that was passed to statsd.timer
        timer_calls = mock_statsd.timer.call_args_list
        pending_time_call = [c for c in timer_calls if "pending_time" in c[0][0]][0]
        actual_pending_time = pending_time_call[0][1]

        # Verify it's a timedelta
        assert isinstance(actual_pending_time, timedelta)

        # Verify it's 30 seconds (while ignoring micro/milliseconds)
        assert 29 <= actual_pending_time.total_seconds() <= 31


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action,action_kwargs,expected_status",
    [
        (JobAction.LAND, {"commit_id": "abc123"}, JobStatus.LANDED),
        (JobAction.FAIL, {"message": "Test failure"}, JobStatus.FAILED),
        (JobAction.DEFER, {"message": "Test defer"}, JobStatus.DEFERRED),
        (JobAction.CANCEL, {}, JobStatus.CANCELLED),
    ],
)
def test_transition_status_sends_status_metric(
    landing_job, action, action_kwargs, expected_status
):
    """Status change metrics are sent when transitioning job status."""
    job = landing_job(JobStatus.SUBMITTED)

    with mock.patch("lando.main.models.jobs.statsd") as mock_statsd:
        job.transition_status(action, **action_kwargs)

        # Verify status metric was sent
        repo_name = job.target_repo.name
        mock_statsd.increment.assert_called_once_with(
            f"lando-api.job.{repo_name}.Landing.status.{expected_status}", 1
        )


@pytest.mark.django_db
def test_job_creation_sends_status_metric(repo_mc):
    """Status metric is sent when a new job is created."""
    with mock.patch("lando.main.models.jobs.statsd") as mock_statsd:
        job = LandingJob(
            status=JobStatus.SUBMITTED,
            revision_to_diff_id={},
            revision_order=[],
            requester_email="test@example.com",
            target_repo=repo_mc(scm_type=SCM_TYPE_GIT),
        )
        job.save()

        # Verify status metric was sent for the creation
        repo_name = job.target_repo.name
        mock_statsd.increment.assert_called_once_with(
            f"lando-api.job.{repo_name}.Landing.status.{JobStatus.SUBMITTED}", 1
        )
