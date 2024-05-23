# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from django.conf import settings
from django.core.mail import EmailMessage

from lando.api.legacy.validation import REVISION_ID_RE

logger = logging.getLogger(__name__)

LANDING_FAILURE_EMAIL_TEMPLATE = """
Your request to land {landing_job_identifier} failed.
{revision_status_details}
Reason:
{reason}
""".strip()


def make_failure_email(
    recipient_email: str,
    landing_job_identifier: str,
    error_msg: str,
) -> EmailMessage:
    """Build a failure EmailMessage.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
        lando_ui_url: The base URL of the Lando website. e.g. https://lando.test
    """
    revision_status_details = ""
    if REVISION_ID_RE.match(landing_job_identifier):
        # If the landing job identifier looks like a Phab revision,
        # link to the relevant view page.
        error_details_location = f"{settings.SITE_URL}/{landing_job_identifier}/"
        revision_status_details = f"\nSee {error_details_location} for details.\n"

    body = LANDING_FAILURE_EMAIL_TEMPLATE.format(
        landing_job_identifier=landing_job_identifier,
        revision_status_details=revision_status_details,
        reason=error_msg,
    )

    msg = EmailMessage(
        subject=f"Lando: Landing of {landing_job_identifier} failed!",
        body=body,
        to=[recipient_email],
    )
    return msg
