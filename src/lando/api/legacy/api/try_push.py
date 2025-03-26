import base64
import binascii
import io
import logging

from django.http import HttpRequest

from lando.api.legacy.hgexports import (
    PATCH_HELPER_MAPPING,
    BugReferencesCheck,
    PatchCollectionAssessor,
    PatchFormat,
    PatchHelper,
    PreventSymlinksCheck,
)
from lando.main.auth import require_authenticated_user, require_permission
from lando.main.models import Repo, Revision
from lando.main.models.landing_job import (
    JobStatus,
    add_job_with_revisions,
)
from lando.main.support import LegacyAPIException

logger = logging.getLogger(__name__)


def build_revision_from_patch_helper(helper: PatchHelper, repo: Repo) -> Revision:
    author, email = helper.parse_author_information()

    timestamp = helper.get_timestamp()

    commit_message = helper.get_commit_description()
    if not commit_message:
        raise ValueError("Patch does not have a commit description.")

    raw_diff = helper.get_diff()

    return Revision.new_from_patch(
        raw_diff=raw_diff,
        patch_data={
            "author_name": author,
            "author_email": email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        },
    )


def decode_json_patch_to_text(patch: str) -> str:
    """Decode from the base64 encoded patch to `str`."""
    try:
        return base64.b64decode(patch.encode("ascii")).decode("utf-8")
    except binascii.Error:
        raise LegacyAPIException(400, "A patch could not be decoded from base64.")


def parse_revisions_from_request(
    patches: list[str], patch_format: PatchFormat, repo: Repo
) -> list[Revision]:
    """Convert a set of base64 encoded patches to `Revision` objects."""
    patches_io = (io.StringIO(decode_json_patch_to_text(patch)) for patch in patches)

    try:
        patch_helpers = [
            PATCH_HELPER_MAPPING[patch_format](patch) for patch in patches_io
        ]
    except ValueError as exc:
        raise LegacyAPIException(
            400,
            "Improper patch format.",
            f"Patch does not match expected format `{patch_format.value}`: {str(exc)}",
        )

    try:
        errors = PatchCollectionAssessor(
            patch_helpers=patch_helpers,
        ).run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[PreventSymlinksCheck],
        )
    except ValueError as exc:
        raise LegacyAPIException(
            400,
            "Error running checks on patch collection.",
            f"Error running checks on patch collection: {str(exc)}",
        )

    if errors:
        bulleted_errors = "\n  - ".join(errors)
        error_message = f"Patch failed checks:\n\n  - {bulleted_errors}"
        raise LegacyAPIException(
            400,
            "Errors found in pre-submission patch checks.",
            error_message,
        )

    try:
        return [
            build_revision_from_patch_helper(patch_helper, repo)
            for patch_helper in patch_helpers
        ]
    except ValueError as exc:
        raise LegacyAPIException(
            400,
            f"Patch does not match expected format `{patch_format.value}`: {str(exc)}",
        )


@require_authenticated_user
@require_permission("scm_level_1")
def post_patches(request: HttpRequest, data: dict):
    # TODO: this endpoint is not currently functional as it will need to
    # have support for token authentication. See bug 1909723.
    base_commit = data["base_commit"]
    patches = data["patches"]
    patch_format = PatchFormat(data["patch_format"])

    environment_repos = Repo.get_mapping()
    try_repo = environment_repos.get("try")
    if not try_repo:
        raise LegacyAPIException(
            500,
            "Could not find a `try` repo to submit to.",
        )

    # Add a landing job for this try push.
    ldap_username = request.user.email
    revisions = parse_revisions_from_request(patches, patch_format, try_repo)
    job = add_job_with_revisions(
        revisions,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        requester_email=ldap_username,
        status=JobStatus.SUBMITTED,
        target_commit_hash=base_commit,
    )
    logger.info(
        f"Created try landing job {job.id} with {len(revisions)} "
        f"changesets against {base_commit} for {ldap_username}."
    )

    return {"id": job.id}, 201
