import logging
import smtplib
import ssl
from datetime import timedelta
from typing import Optional

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.db import transaction
from django.utils import timezone

from lando.api.legacy.email import (
    make_failure_email,
    make_job_aborted_email,
    make_uplift_failure_email,
    make_uplift_success_email,
)
from lando.main.models.jobs import JobAction, JobStatus
from lando.main.models.uplift import HackbotResolution, UpliftJob
from lando.utils import hackbot
from lando.utils.celery import app as celery_app
from lando.utils.phabricator import (
    PhabricatorClient,
    PhabricatorCommunicationException,
)

logger = logging.getLogger(__name__)

# How long an uplift job may wait on a Hackbot run before Lando gives up on it.
HACKBOT_RUN_TIMEOUT = timedelta(hours=24)

# Seconds between polls of a Hackbot run, until Hackbot can notify Lando itself.
HACKBOT_POLL_INTERVAL = 60


@celery_app.task
def debug_task() -> int:
    """A simple debug task to test celery functionality.

    To queue this task, import it and call `debug_task.apply_async()`.
    """
    print("hello")
    return 1


@celery_app.task(
    # Auto-retry for errors from the SMTP socket connection. Don't log
    # stack traces.  All other exceptions will log a stack trace and cause an
    # immediate job failure without retrying.
    autoretry_for=(IOError, smtplib.SMTPException, ssl.SSLError),
    # Seconds to wait between retries.
    default_retry_delay=60,
    # Retry sending the notification for three days.  This is the same effort
    # that SMTP servers use for their outbound mail queues.
    max_retries=60 * 24 * 3,
    # Don't store the success or failure results.
    ignore_result=True,
    # Don't ack jobs until the job is complete. This should only come up if a worker
    # dies suddenly in the middle of an email job.  If it does die then it is possible
    # for the user to get two emails (harmless), which is better than them receiving
    # no emails.
    acks_late=True,
)
def send_landing_failure_email(
    recipient_email: str, landing_job_identifier: str, error_msg: str
):
    """Tell a user that the Transplant service couldn't land their code.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
    """
    with mail.get_connection() as c:
        c.send_messages(
            [
                make_failure_email(
                    recipient_email,
                    landing_job_identifier,
                    error_msg,
                )
            ]
        )

    logger.info(f"Notification email sent to {recipient_email}")


@celery_app.task(
    # Auto-retry for errors from the SMTP socket connection. Don't log
    # stack traces.  All other exceptions will log a stack trace and cause an
    # immediate job failure without retrying.
    autoretry_for=(IOError, smtplib.SMTPException, ssl.SSLError),
    # Seconds to wait between retries.
    default_retry_delay=60,
    # Retry sending the notification for three days.  This is the same effort
    # that SMTP servers use for their outbound mail queues.
    max_retries=60 * 24 * 3,
    # Don't store the success or failure results.
    ignore_result=True,
    # Don't ack jobs until the job is complete. This should only come up if a worker
    # dies suddenly in the middle of an email job.  If it does die then it is possible
    # for the user to get two emails (harmless), which is better than them receiving
    # no emails.
    acks_late=True,
)
def send_bug_update_failure_email(
    recipient_email: str, landing_job_identifier: str, error_msg: str
):
    """Tell a user that Lando couldn't update bugs post-uplift.

    Args:
        recipient_email: The email of the user receiving the bug update notification.
        revision_id: The Phabricator Revision ID that failed to update bugs. e.g. D12345
        error_msg: The error message returned by Bugzilla.
    """
    with mail.get_connection() as c:
        c.send_messages(
            [
                make_failure_email(
                    recipient_email,
                    landing_job_identifier,
                    error_msg,
                )
            ]
        )

    logger.info(f"Notification email sent to {recipient_email}")


@celery_app.task(
    autoretry_for=(IOError, smtplib.SMTPException, ssl.SSLError),
    default_retry_delay=60,
    max_retries=60 * 24 * 3,
    ignore_result=True,
    acks_late=True,
)
def send_job_aborted_email(
    recipient_email: str, job_type: str, job_id: int, job_url: str, error: str
):
    """Tell a user that Lando gave up retrying their job.

    Args:
        recipient_email: The email of the user receiving the notification.
        job_type: Human-friendly name of the type of job, e.g. "Landing".
        job_id: The ID of the aborted job.
        job_url: URL of the job details page.
        error: The error recorded on the job when it was aborted.
    """
    if not recipient_email:
        logger.warning(
            f"Skipping aborted email for {job_type} job {job_id} without a requester."
        )
        return

    with mail.get_connection() as connection:
        connection.send_messages(
            [
                make_job_aborted_email(
                    recipient_email,
                    job_type,
                    job_id,
                    job_url,
                    error,
                )
            ]
        )

    logger.info(
        f"Aborted {job_type} job {job_id} notification email sent to {recipient_email}"
    )


@celery_app.task(
    autoretry_for=(IOError, smtplib.SMTPException, ssl.SSLError),
    default_retry_delay=60,
    max_retries=60 * 24 * 3,
    ignore_result=True,
    acks_late=True,
)
def send_uplift_failure_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    reason: str,
    requested_revision_ids: list[int],
):
    """Notify a user that an uplift job failed.

    Args:
        recipient_email: Email address to send the notification to.
        repo_name: Name of the target repository.
        job_url: URL to view the job details.
        reason: Error message describing why the uplift failed.
        requested_revision_ids: List of Phabricator revision IDs that were being uplifted.
    """
    if not recipient_email:
        logger.info("Skipping uplift failure email because recipient email is empty")
        return

    with mail.get_connection() as connection:
        connection.send_messages(
            [
                make_uplift_failure_email(
                    recipient_email,
                    repo_name,
                    job_url,
                    reason,
                    requested_revision_ids,
                )
            ]
        )

    logger.info("Uplift failure email sent to %s", recipient_email)


@celery_app.task(
    autoretry_for=(IOError, smtplib.SMTPException, ssl.SSLError),
    default_retry_delay=60,
    max_retries=60 * 24 * 3,
    ignore_result=True,
    acks_late=True,
)
def send_uplift_success_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    created_revision_ids: list[int],
    requested_revision_ids: list[int],
):
    """Notify a user that an uplift job succeeded."""
    if not recipient_email:
        logger.info("Skipping uplift success email because recipient email is empty")
        return

    with mail.get_connection() as connection:
        connection.send_messages(
            [
                make_uplift_success_email(
                    recipient_email,
                    repo_name,
                    job_url,
                    created_revision_ids,
                    requested_revision_ids,
                )
            ]
        )

    logger.info("Uplift success email sent to %s", recipient_email)


@celery_app.task(
    autoretry_for=(IOError, PhabricatorCommunicationException),
    default_retry_delay=20,
    acks_late=True,
    ignore_result=True,
    # Retry 3 times every 2 seconds.
    max_retries=3 * 20,
)
def admin_remove_phab_project(
    revision_phid: str, project_phid: str, comment: Optional[str] = None
):
    """Remove a project tag from the provided revision.

    Note, this uses administrator privileges and should only be called
    if permissions checking is handled elsewhere.

    Args:
        revision_phid: phid of the revision to remove the project tag from.
        project_phid: phid of the project to remove.
        comment: An optional comment to add when removing the project.
    """
    transactions = [{"type": "projects.remove", "value": [project_phid]}]
    if comment is not None:
        transactions.append({"type": "comment", "value": comment})

    privileged_phab = PhabricatorClient(
        settings.PHABRICATOR_URL,
        settings.PHABRICATOR_ADMIN_API_KEY,
    )
    # We only retry for PhabricatorCommunicationException, rather than the
    # base PhabricatorAPIException to treat errors in this implementation as
    # fatal.
    privileged_phab.call_conduit(
        "differential.revision.edit",
        objectIdentifier=revision_phid,
        transactions=transactions,
    )


@celery_app.task(
    autoretry_for=(IOError, PhabricatorCommunicationException),
    default_retry_delay=3,
    acks_late=True,
    ignore_result=True,
)
def phab_trigger_repo_update(repo_identifier: str):
    """Trigger a repo update in Phabricator's backend."""
    # Tell Phabricator to scan the landing repo so revisions are closed quickly.
    phab = PhabricatorClient(
        settings.PHABRICATOR_URL,
        settings.PHABRICATOR_ADMIN_API_KEY,
    )
    phab.call_conduit("diffusion.looksoon", repositories=[repo_identifier])


@celery_app.task(
    autoretry_for=(IOError, PhabricatorCommunicationException),
    default_retry_delay=20,
    acks_late=True,
    ignore_result=True,
    # Retry 3 times every 2 seconds.
    max_retries=3 * 20,
)
def set_uplift_request_form_on_revision(
    revision_id: int, uplift_form_str: str, user_id: int
):
    """Send the contents of an uplift request form to Phabricator.

    Update the uplift request form on revision `D<revision_id>` to
    the value `uplift_form_str`, using the `phab_api_key` for the
    user.
    """
    try:
        user = User.objects.select_related("profile").get(pk=user_id)
    except User.DoesNotExist as exc:
        raise RuntimeError(f"User {user_id} does not exist.") from exc

    logging.info(f"Sending uplift request form update to {revision_id=}.")

    # Create a `PhabricatorClient` using the user's API key.
    phab = PhabricatorClient(
        settings.PHABRICATOR_URL,
        user.profile.phabricator_api_key,
    )

    phab.call_conduit(
        "differential.revision.edit",
        # `objectIdentifier` accepts revision ID numbers as well as PHIDs.
        objectIdentifier=revision_id,
        transactions=[{"type": "uplift.request", "value": uplift_form_str}],
    )

    logging.info(
        f"Uplift request assessment updated on Phabricator by {user.email} for {revision_id=}."
    )


@celery_app.task(
    autoretry_for=(IOError, PhabricatorCommunicationException),
    default_retry_delay=20,
    acks_late=True,
    ignore_result=True,
    # Retry 3 times every 2 seconds.
    max_retries=3 * 20,
)
def request_ai_change_approval(revision_id: int, request: dict):
    """Ask for approval of an AI change in `D<revision_id>`.

    Lando sends the request as its own automation user, so Phabricator records it
    as automation rather than as the uplift requester. A request without a
    `changeDiffID` is made on the revision's active diff.
    """
    logger.debug(f"Requesting approval of an AI change on {revision_id=}.")
    phab = PhabricatorClient(
        settings.PHABRICATOR_URL,
        settings.PHABRICATOR_ADMIN_API_KEY,
    )
    if "changeDiffID" not in request:
        logger.debug(f"Looking up the active diff of {revision_id=}.")
        revision = phab.single(
            phab.call_conduit(
                "differential.revision.search", constraints={"ids": [revision_id]}
            ),
            "data",
        )
        request = {
            **request,
            "changeDiffID": phab.expect(revision, "fields", "diffID"),
        }

    phab.call_conduit(
        "differential.revision.edit",
        objectIdentifier=revision_id,
        transactions=[{"type": "ai-change.request", "value": request}],
    )
    logger.info(f"Lando requested approval of an AI change on {revision_id=}.")


@celery_app.task(ignore_result=True, acks_late=True)
def poll_hackbot_resolution(resolution_id: int):
    """Check on a Hackbot resolution's run, re-queueing itself until the run finishes.

    Each waiting job has its own chain of polls, which ends once its run finishes,
    so nothing runs while no job is waiting. A Hackbot webhook will replace this.
    The job fails once `HACKBOT_RUN_TIMEOUT` passes, even if Hackbot can't be reached.
    """
    resolution = (
        HackbotResolution.objects.select_related("job").filter(pk=resolution_id).first()
    )
    if resolution is None or resolution.job.status != JobStatus.WAITING:
        logger.info(f"Stopped polling Hackbot resolution {resolution_id}.")
        return

    try:
        finished = check_hackbot_resolution(resolution)
    except requests.RequestException:
        logger.exception(
            f"Could not poll the Hackbot run for {resolution}, trying again.",
            extra={
                "job_id": resolution.job_id,
                "hackbot_run_id": str(resolution.run_id),
            },
        )
        finished = False

    if finished:
        return

    if timezone.now() - resolution.created_at > HACKBOT_RUN_TIMEOUT:
        fail_hackbot_resolution(resolution, "Hackbot did not finish in time.")
        return

    poll_hackbot_resolution.apply_async(
        args=(resolution_id,), countdown=HACKBOT_POLL_INTERVAL
    )


def requeue_hackbot_resolution_polls():
    """Start polling again for every job waiting on Hackbot.

    A chain of polls ends if a Celery worker loses its task, so the uplift worker
    calls this as it starts. A duplicate chain stops once its job stops waiting.
    """
    for job in UpliftJob.objects.filter(status=JobStatus.WAITING):
        resolution = job.hackbot_resolution
        if resolution is not None:
            logger.info(f"Polling Hackbot again for {resolution}.")
            poll_hackbot_resolution.apply_async(args=(resolution.id,))


def check_hackbot_resolution(resolution: HackbotResolution) -> bool:
    """Resubmit or fail the resolution's job once its run finishes.

    Returns whether the run finished, so polling can stop.
    """
    job = resolution.job
    logger.debug(f"Polling Hackbot run {resolution.run_id} for {job}.")
    run = hackbot.get_run(str(resolution.run_id))

    if not run.is_finished:
        return False

    resolution.findings = run.findings
    if not run.succeeded:
        fail_hackbot_resolution(
            resolution, f"The Hackbot run ended with: {run.error or run.status}"
        )
        return True

    result = resolution.result
    if not result.resolved:
        problems = ", ".join(result.unresolved + result.verification_failures)
        fail_hackbot_resolution(
            resolution, f"Hackbot left conflicts unresolved: {problems or 'unknown'}"
        )
        return True

    logger.debug(f"Downloading the resolved patch for {job}.")
    resolution.patch = hackbot.get_artifact(
        str(resolution.run_id), hackbot.PATCH_ARTIFACT
    )
    with transaction.atomic():
        job = lock_waiting_job(resolution)
        if job is None:
            return True
        resolution.save()
        job.transition_status(JobAction.RESUBMIT)
    logger.info(
        f"Resubmitted {job} with Hackbot's resolution.",
        extra={"job_id": job.id, "hackbot_run_id": str(resolution.run_id)},
    )
    return True


def fail_hackbot_resolution(resolution: HackbotResolution, reason: str):
    """Fail an uplift job whose merge conflict Hackbot did not resolve.

    The job keeps the merge conflict recorded when it was handed off, so the
    user is left with the same breakdown as a job that never tried Hackbot.
    """
    with transaction.atomic():
        job = lock_waiting_job(resolution)
        if job is None:
            return
        logger.warning(
            f"Hackbot did not resolve the merge conflict for {job}: {reason}",
            extra={"job_id": job.id, "hackbot_run_id": str(resolution.run_id)},
        )
        resolution.save()
        job.transition_status(
            JobAction.FAIL,
            message=f"{reason}\n\n{job.error}",
        )
    send_uplift_failure_email.apply_async(
        args=(
            job.submission.requested_by.email,
            job.target_repo.name,
            job.url(),
            job.error,
            job.submission.requested_revision_ids,
        )
    )


def lock_waiting_job(resolution: HackbotResolution) -> UpliftJob | None:
    """Lock the resolution's job, returning it only if it's still waiting on Hackbot.

    Polls of the same job can overlap, so each re-reads the job under a lock before
    moving it on, rather than saving a stale copy over a newer status.
    """
    job = UpliftJob.objects.select_for_update().get(pk=resolution.job_id)
    if job.status != JobStatus.WAITING:
        logger.info(
            f"Not moving {job} on, as it is no longer waiting on Hackbot.",
            extra={"job_id": job.id, "hackbot_run_id": str(resolution.run_id)},
        )
        return None

    resolution.job = job
    return job
