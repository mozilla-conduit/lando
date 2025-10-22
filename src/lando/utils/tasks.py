import logging
import smtplib
import ssl
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail

from lando.api.legacy.email import (
    make_failure_email,
    make_uplift_failure_email,
    make_uplift_success_email,
)
from lando.utils.celery import app as celery_app
from lando.utils.phabricator import (
    PhabricatorClient,
    PhabricatorCommunicationException,
)

logger = logging.getLogger(__name__)


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
def send_uplift_failure_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    reason: str,
    conflict_sections: list[dict[str, str]] | None = None,
):
    """Notify a user that an uplift job failed."""

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
                    conflict_sections,
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
    created_revision_ids: list[str],
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
    except User.NotFoundError as exc:
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
