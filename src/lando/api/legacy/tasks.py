# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
import ssl
from typing import Optional

from django.conf import settings
from django.core import mail

from lando.api.legacy.celery import celery
from lando.api.legacy.email import make_failure_email
from lando.api.legacy.phabricator import (
    PhabricatorClient,
    PhabricatorCommunicationException,
)

logger = logging.getLogger(__name__)


@celery.task(
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


@celery.task(
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


@celery.task(
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


@celery.task(
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
