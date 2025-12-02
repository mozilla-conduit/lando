import logging

from django.conf import settings
from django.core.mail import EmailMessage

from lando.api.legacy.validation import REVISION_ID_RE
from lando.utils.const import UPLIFT_DOCS_URL

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


UPLIFT_FAILURE_EMAIL_TEMPLATE = f"""
Your uplift request for {{repo_name}} did not complete successfully.

See here for details and merge conflicts: {{job_url}}

Reason:
{{reason}}

Review the job details linked above for more information, including
details of any merge conflicts that were encountered.

If your uplift failed due to merge conflicts, this means your patch
cannot be uplifted without manually resolving the merge conflicts and
re-submitting. Please pull the latest changes for {{repo_name}}, resolve
the conflicts locally, and submit a new uplift request using `moz-phab
uplift` once the conflicts are cleared.

Once you have created a new uplift Phabricator revision, you can use the
"Link Existing Assessment" button to link your new uplift revision to the
uplift assessment form you previously submitted.

See {UPLIFT_DOCS_URL}
for step-by-step instructions.
""".strip()

UPLIFT_SUCCESS_EMAIL_TEMPLATE = """
Your uplift request for {repo_name} finished successfully.

Requested revisions:
{requested_revision_lines}

Lando created the following revisions:
{created_revision_lines}

You can review the full job details at {job_url}.

Thank you for keeping the uplift train moving!
""".strip()


def make_uplift_failure_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    reason: str,
    requested_revision_ids: list[int],
) -> EmailMessage:
    """Build an uplift failure email.

    Args:
        recipient_email: Email address to send the failure notification to.
        repo_name: Name of the target repository (e.g., "firefox-beta").
        job_url: URL to view the job details.
        reason: Error message describing why the uplift failed.
        requested_revision_ids: Optional list of original revision IDs that were being uplifted.
    """
    body = UPLIFT_FAILURE_EMAIL_TEMPLATE.format(
        job_url=job_url,
        reason=reason,
        repo_name=repo_name,
    )

    # Get the tip revision for the subject line.
    subject_suffix = (
        f" (D{requested_revision_ids[-1]})" if requested_revision_ids else ""
    )

    msg = EmailMessage(
        subject=f"Lando: Uplift for {repo_name} failed{subject_suffix}",
        body=body,
        to=[recipient_email],
    )
    return msg


def make_uplift_success_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    created_revision_ids: list[int],
    requested_revision_ids: list[int],
) -> EmailMessage:
    """Build an uplift success email."""
    requested_revision_lines = format_revision_id_lines(requested_revision_ids)
    created_revision_lines = format_revision_id_lines(created_revision_ids)

    # Get the tip revision for the subject line.
    subject_suffix = (
        f" (D{requested_revision_ids[-1]})" if requested_revision_ids else ""
    )

    body = UPLIFT_SUCCESS_EMAIL_TEMPLATE.format(
        repo_name=repo_name,
        job_url=job_url,
        created_revision_lines=created_revision_lines,
        requested_revision_lines=requested_revision_lines,
    )

    msg = EmailMessage(
        subject=f"Lando: Uplift for {repo_name} succeeded{subject_suffix}",
        body=body,
        to=[recipient_email],
    )
    return msg


def format_revision_id_lines(revision_ids: list[int]) -> str:
    """Format revision IDs as a list for email."""
    return "\n".join(f"- D{rev_id}" for rev_id in revision_ids)
