import base64
import binascii
import enum
import io
import logging

from django.conf import settings
from django.http import HttpRequest

from lando.api.legacy.hgexports import (
    GitPatchHelper,
    HgPatchHelper,
    PatchHelper,
)
from lando.api.legacy.repos import (
    get_repos_for_env,
)
from lando.main.auth import require_authenticated_user, require_permission
from lando.main.models.landing_job import (
    LandingJobStatus,
    add_job_with_revisions,
)
from lando.main.models.revision import Revision
from lando.main.support import LegacyAPIException

logger = logging.getLogger(__name__)


@enum.unique
class PatchFormat(enum.Enum):
    """Enumeration of the acceptable types of patches."""

    GitFormatPatch = "git-format-patch"
    HgExport = "hgexport"


PATCH_HELPER_MAPPING = {
    PatchFormat.GitFormatPatch: GitPatchHelper,
    PatchFormat.HgExport: HgPatchHelper,
}


def build_revision_from_patch_helper(helper: PatchHelper) -> Revision:
    author, email = helper.parse_author_information()

    timestamp = helper.get_timestamp()

    commit_message = helper.get_commit_description()
    if not commit_message:
        raise ValueError("Patch does not have a commit description.")

    return Revision.new_from_patch(
        raw_diff=helper.get_diff(),
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
    patches: list[str], patch_format: PatchFormat
) -> list[Revision]:
    """Convert a set of base64 encoded patches to `Revision` objects."""
    patches_io = (io.StringIO(decode_json_patch_to_text(patch)) for patch in patches)

    patch_helpers = (PATCH_HELPER_MAPPING[patch_format](patch) for patch in patches_io)

    try:
        return [
            build_revision_from_patch_helper(patch_helper)
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

    environment_repos = get_repos_for_env(settings.ENVIRONMENT)
    try_repo = environment_repos.get("try")
    if not try_repo:
        raise LegacyAPIException(
            500,
            "Could not find a `try` repo to submit to.",
        )

    # Add a landing job for this try push.
    ldap_username = request.user.email
    revisions = parse_revisions_from_request(patches, patch_format)
    job = add_job_with_revisions(
        revisions,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        requester_email=ldap_username,
        status=LandingJobStatus.SUBMITTED,
        target_commit_hash=base_commit,
    )
    logger.info(
        f"Created try landing job {job.id} with {len(revisions)} "
        f"changesets against {base_commit} for {ldap_username}."
    )

    return {"id": job.id}, 201
