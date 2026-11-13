from collections.abc import Callable
from datetime import timedelta
from unittest import mock

import pytest
import requests_mock
from django.conf import settings
from django.utils import timezone

from lando.main.models import JobStatus
from lando.main.models.uplift import HackbotResolution, UpliftJob
from lando.main.scm import SCMType
from lando.utils.hackbot import PATCH_ARTIFACT
from lando.utils.tasks import (
    HACKBOT_POLL_INTERVAL,
    poll_hackbot_resolution,
    requeue_hackbot_resolution_polls,
)

RUN_ID = "0b6c1f4e-6c1a-4bd4-9a77-3c1d1f3f4d10"
RUN_URL = f"{settings.HACKBOT_URL}/runs/{RUN_ID}"
SIGNED_PATCH_URL = "https://storage.test/changes.patch?signature=abc"
RESOLVED_PATCH = "From 1234 Mon Sep 17 00:00:00 2001\nSubject: resolved\n"

RESOLVED_FINDINGS = {
    "resolved": True,
    "confidence": "high",
    "summary": "Kept the tip's rename and applied the fix on top.",
    "conflicts": [{"file": "README", "resolution": "Kept both changes."}],
    "unresolved": [],
}


@pytest.fixture
def waiting_resolution(
    repo_mc: Callable,
    user,
    create_patch_revision: Callable,
    make_uplift_job_with_revisions: Callable,
    make_hackbot_resolution: Callable,
) -> HackbotResolution:
    repo = repo_mc(SCMType.GIT, name="firefox-beta", approval_required=True)
    revision = create_patch_revision(1)
    job = make_uplift_job_with_revisions(repo, user, [revision])
    job.status = JobStatus.WAITING
    job.error = "Problem while applying patch in revision 1."
    job.save()
    return make_hackbot_resolution(job, revision, run_id=RUN_ID)


@pytest.fixture
def mock_failure_email(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    failure_email = mock.MagicMock()
    monkeypatch.setattr("lando.utils.tasks.send_uplift_failure_email", failure_email)
    return failure_email


@pytest.fixture
def mock_requeue(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Catch the poll re-queueing itself, which Celery would run eagerly in tests."""
    requeue = mock.MagicMock()
    monkeypatch.setattr(poll_hackbot_resolution, "apply_async", requeue)
    return requeue


def run_document(status: str, findings: dict | None = None, error: str = "") -> dict:
    return {
        "run_id": RUN_ID,
        "agent": "uplift-resolve",
        "status": status,
        "summary": {"status": "ok", "findings": findings or {}, "actions": []},
        "error": error or None,
    }


@pytest.mark.django_db
def test_poll_requeues_itself_while_the_run_is_going(
    waiting_resolution: HackbotResolution, mock_requeue: mock.MagicMock
):
    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=run_document("running"))

        poll_hackbot_resolution(waiting_resolution.id)

    waiting_resolution.job.refresh_from_db()
    assert waiting_resolution.job.status == JobStatus.WAITING, (
        "A job whose run is still going should keep waiting."
    )
    mock_requeue.assert_called_once_with(
        args=(waiting_resolution.id,), countdown=HACKBOT_POLL_INTERVAL
    )


@pytest.mark.django_db
def test_poll_resubmits_a_resolved_job_with_the_patch(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
):
    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=run_document("succeeded", RESOLVED_FINDINGS))
        mocker.get(
            f"{RUN_URL}/artifacts/{PATCH_ARTIFACT}", json={"url": SIGNED_PATCH_URL}
        )
        mocker.get(SIGNED_PATCH_URL, text=RESOLVED_PATCH)

        poll_hackbot_resolution(waiting_resolution.id)

    waiting_resolution.refresh_from_db()
    job = waiting_resolution.job
    job.refresh_from_db()
    assert job.status == JobStatus.SUBMITTED, (
        "A resolved job should go back in the queue for the worker."
    )
    assert waiting_resolution.patch == RESOLVED_PATCH, (
        "Hackbot's resolved patch should be saved on the resolution."
    )
    assert waiting_resolution.findings == RESOLVED_FINDINGS, (
        "Hackbot's findings should be saved on the resolution."
    )
    assert job.has_hackbot_resolution, (
        "The resubmitted job should be recognised as having a resolution."
    )
    mock_failure_email.apply_async.assert_not_called()
    mock_requeue.assert_not_called()


@pytest.mark.django_db
def test_poll_leaves_a_job_another_poll_already_moved_on(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
):
    job = waiting_resolution.job

    def land_job_during_download(request, context) -> str:
        """Land the job as if a duplicate poll resubmitted it and the worker ran."""
        UpliftJob.objects.filter(pk=job.pk).update(
            status=JobStatus.LANDED, created_revision_ids=[7000]
        )
        return RESOLVED_PATCH

    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=run_document("succeeded", RESOLVED_FINDINGS))
        mocker.get(
            f"{RUN_URL}/artifacts/{PATCH_ARTIFACT}", json={"url": SIGNED_PATCH_URL}
        )
        mocker.get(SIGNED_PATCH_URL, text=land_job_during_download)

        poll_hackbot_resolution(waiting_resolution.id)

    job.refresh_from_db()
    assert job.status == JobStatus.LANDED, (
        "A stale poll should not put a landed job back in the queue."
    )
    assert job.created_revision_ids == [7000], (
        "A stale poll should keep the revisions the landed job created."
    )
    mock_requeue.assert_not_called()


@pytest.mark.django_db
def test_poll_does_not_fail_a_job_another_poll_already_moved_on(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
):
    job = waiting_resolution.job

    def resubmit_job_during_poll(request, context) -> dict:
        """Resubmit the job as if a duplicate poll found the run resolved."""
        UpliftJob.objects.filter(pk=job.pk).update(status=JobStatus.SUBMITTED)
        return run_document("failed", error="sandbox crashed")

    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=resubmit_job_during_poll)

        poll_hackbot_resolution(waiting_resolution.id)

    job.refresh_from_db()
    assert job.status == JobStatus.SUBMITTED, (
        "A stale poll should not fail a job that was already resubmitted."
    )
    mock_failure_email.apply_async.assert_not_called()


@pytest.mark.django_db
def test_poll_fails_a_job_hackbot_left_unresolved(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
):
    findings = {
        **RESOLVED_FINDINGS,
        "resolved": False,
        "unresolved": ["README"],
        "verification_failures": ["build failed"],
    }

    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=run_document("succeeded", findings))

        poll_hackbot_resolution(waiting_resolution.id)

    waiting_resolution.refresh_from_db()
    job = waiting_resolution.job
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED, (
        "A job Hackbot could not resolve should fail."
    )
    assert job.error.startswith(
        "Hackbot left conflicts unresolved: README, build failed"
    ), "The error should name what Hackbot couldn't resolve, and what its checks found."
    assert "Problem while applying patch in revision 1." in job.error, (
        "The error should keep the original merge conflict."
    )
    assert waiting_resolution.findings == findings, (
        "Hackbot's findings should be kept to explain the failure."
    )
    assert not waiting_resolution.patch, "No patch should be saved."
    mock_failure_email.apply_async.assert_called_once()
    mock_requeue.assert_not_called()


@pytest.mark.django_db
def test_poll_fails_a_job_whose_run_failed(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
):
    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=run_document("failed", error="sandbox crashed"))

        poll_hackbot_resolution(waiting_resolution.id)

    job = waiting_resolution.job
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED, "A failed run should fail the job."
    assert job.error.startswith("The Hackbot run ended with: sandbox crashed"), (
        "The error should carry Hackbot's reason."
    )
    mock_failure_email.apply_async.assert_called_once()
    mock_requeue.assert_not_called()


@pytest.mark.django_db
def test_poll_fails_a_job_whose_run_took_too_long(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
):
    HackbotResolution.objects.filter(pk=waiting_resolution.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )

    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, json=run_document("running"))

        poll_hackbot_resolution(waiting_resolution.id)

    job = waiting_resolution.job
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED, "A run that never finishes should fail."
    assert job.error.startswith("Hackbot did not finish in time."), (
        "The error should say Hackbot timed out."
    )
    mock_requeue.assert_not_called()


@pytest.mark.parametrize(
    "mock_hackbot",
    (
        pytest.param(
            lambda mocker: mocker.get(RUN_URL, status_code=503),
            id="unreachable",
        ),
        pytest.param(
            lambda mocker: (
                mocker.get(RUN_URL, json=run_document("succeeded", RESOLVED_FINDINGS)),
                mocker.get(f"{RUN_URL}/artifacts/{PATCH_ARTIFACT}", status_code=404),
            ),
            id="missing-artifact",
        ),
    ),
)
@pytest.mark.django_db
def test_poll_fails_a_job_it_could_not_finish_in_time(
    waiting_resolution: HackbotResolution,
    mock_failure_email: mock.MagicMock,
    mock_requeue: mock.MagicMock,
    mock_hackbot: Callable,
):
    HackbotResolution.objects.filter(pk=waiting_resolution.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    waiting_resolution.refresh_from_db()

    with requests_mock.mock() as mocker:
        mock_hackbot(mocker)

        poll_hackbot_resolution(waiting_resolution.id)

    job = waiting_resolution.job
    job.refresh_from_db()
    assert job.status == JobStatus.FAILED, (
        "A job whose polls keep failing should fail once the run times out."
    )
    assert job.error.startswith("Hackbot did not finish in time."), (
        "The error should say Hackbot timed out."
    )
    mock_failure_email.apply_async.assert_called_once()
    mock_requeue.assert_not_called()


@pytest.mark.django_db
def test_poll_requeues_itself_when_hackbot_is_unreachable(
    waiting_resolution: HackbotResolution, mock_requeue: mock.MagicMock
):
    with requests_mock.mock() as mocker:
        mocker.get(RUN_URL, status_code=503)

        poll_hackbot_resolution(waiting_resolution.id)

    waiting_resolution.job.refresh_from_db()
    assert waiting_resolution.job.status == JobStatus.WAITING, (
        "A failed poll should leave the job waiting."
    )
    mock_requeue.assert_called_once_with(
        args=(waiting_resolution.id,), countdown=HACKBOT_POLL_INTERVAL
    )


@pytest.mark.django_db
def test_poll_stops_once_the_job_is_no_longer_waiting(
    waiting_resolution: HackbotResolution, mock_requeue: mock.MagicMock
):
    waiting_resolution.job.status = JobStatus.CANCELLED
    waiting_resolution.job.save()

    with requests_mock.mock() as mocker:
        poll_hackbot_resolution(waiting_resolution.id)

        assert not mocker.called, "A job that stopped waiting shouldn't be polled."
    mock_requeue.assert_not_called()


@pytest.mark.django_db
def test_requeue_hackbot_resolution_polls_restarts_waiting_jobs(
    waiting_resolution: HackbotResolution, mock_requeue: mock.MagicMock
):
    requeue_hackbot_resolution_polls()

    mock_requeue.assert_called_once_with(args=(waiting_resolution.id,))
