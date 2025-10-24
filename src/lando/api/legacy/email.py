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


UPLIFT_FAILURE_EMAIL_TEMPLATE = """
Your uplift request for {repo_name} did not complete successfully.

Job details: {job_url}

Reason:
{reason}

{resolution_instructions}
""".strip()

UPLIFT_CONFLICT_INSTRUCTIONS_TEMPLATE = """
Lando detected merge conflicts while applying your stack. This
means your patch cannot be uplifted without manually resolving
the merge conflicts and re-submitting. Please pull the latest
changes for {repo_name}, resolve the conflicts locally,
and submit a new uplift request using `moz-phab uplift`
once the conflicts are cleared.

See https://wiki.mozilla.org/index.php?title=Release_Management/Requesting_an_Uplift
for step-by-step instructions.

Conflict markers were reported in:
{conflict_summary}
""".strip()

UPLIFT_CONFLICT_SECTION_TEMPLATE = """
- {path}
{snippet}
""".strip()

UPLIFT_GENERIC_RESOLUTION = """
Review the job details linked above, address the failure in
your patch stack, and resubmit the uplift request when ready.
""".strip()

UPLIFT_SUCCESS_EMAIL_TEMPLATE = """
Your uplift request for {repo_name} finished successfully.

Lando created the following revisions:
{revision_lines}

You can review the full job details at {job_url}.

Thank you for keeping the uplift train moving!
""".strip()


def build_uplift_conflict_summary(conflict_sections: list[dict[str, str]]) -> str:
    """Build a conflict summary for display in the uplift failure email."""
    formatted = []
    for section in conflict_sections:
        path = section.get("path", "Unknown file")
        snippet = section.get("snippet", "").strip()
        snippet = snippet or "(No conflict markers were captured.)"

        formatted.append(
            UPLIFT_CONFLICT_SECTION_TEMPLATE.format(path=path, snippet=snippet)
        )

    return "\n\n".join(formatted)


def make_uplift_failure_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    reason: str,
    conflict_sections: list[dict[str, str]] | None = None,
) -> EmailMessage:
    """Build an uplift failure email."""
    if conflict_sections is not None:
        conflict_summary = build_uplift_conflict_summary(conflict_sections)
        resolution_instructions = UPLIFT_CONFLICT_INSTRUCTIONS_TEMPLATE.format(
            repo_name=repo_name,
            conflict_summary=conflict_summary,
        )
    else:
        resolution_instructions = UPLIFT_GENERIC_RESOLUTION

    body = UPLIFT_FAILURE_EMAIL_TEMPLATE.format(
        repo_name=repo_name,
        job_url=job_url,
        reason=reason,
        resolution_instructions=resolution_instructions,
    )

    msg = EmailMessage(
        subject=f"Lando: Uplift for {repo_name} failed",
        body=body,
        to=[recipient_email],
    )
    return msg


def make_uplift_success_email(
    recipient_email: str,
    repo_name: str,
    job_url: str,
    created_revision_ids: list[str],
) -> EmailMessage:
    """Build an uplift success email."""
    revision_lines = "\n".join(f"- {rev_id}" for rev_id in created_revision_ids)
    body = UPLIFT_SUCCESS_EMAIL_TEMPLATE.format(
        repo_name=repo_name,
        job_url=job_url,
        revision_lines=revision_lines,
    )

    msg = EmailMessage(
        subject=f"Lando: Uplift for {repo_name} succeeded",
        body=body,
        to=[recipient_email],
    )
    return msg
