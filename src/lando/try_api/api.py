import base64
import binascii
import io
import json
import logging
import time
from typing import Annotated

from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import redirect
from ninja import NinjaAPI, Schema
from pydantic import Field, StringConstraints

from lando.main.models import Repo
from lando.main.models.commit_map import CommitMap
from lando.main.models.jobs import JobStatus
from lando.main.models.landing_job import LandingJob, add_revisions_to_job
from lando.main.models.revision import Revision
from lando.main.scm.consts import SCMType
from lando.main.scm.helpers import PATCH_HELPER_MAPPING, PatchFormat
from lando.utils.exceptions import (
    BadRequestProblemException,
    ForbiddenProblemException,
    ProblemDetail,
    ProblemException,
    problem_exception_handler,
)
from lando.utils.landing_checks import LandingChecks
from lando.utils.ninja_auth import AccessTokenAuth

logger = logging.getLogger(__name__)

# During the Try hg->git migration each Try push lands on both its Hg repo and a
# Git backing repo. This maps the (Hg) Try repo name to its Git backing repo.
GIT_BACKING_REPOS = {
    "try": "try-backing",
}

# File used to record the paired Git backing landing job ID on the Hg Try push.
GIT_BACKING_JOB_FILE = "lando_git_backing.json"

api = NinjaAPI(auth=AccessTokenAuth(), urls_namespace="try")


@api.exception_handler(PermissionDenied)
def on_permission_denied(request: WSGIRequest, exc: PermissionDenied) -> HttpResponse:
    """Create a 403 JSON response when the API raises a PermissionDenied."""
    return problem_exception_handler(
        request, ForbiddenProblemException.from_permission_denied(exc)
    )


api.exception_handler(ProblemException)(problem_exception_handler)


Base64Patch = Annotated[
    str, Field(description="Base64 encoded patch.", pattern=r"^[A-Za-z0-9+/]+={0,2}$")
]


def get_commit_map(try_repo_scm_type: str, repo_name: str, repo_scm_type: str) -> str:
    """Return the repo to use for commit mapping, or raise `ValueError` if unsupported."""
    mapping_repo = CommitMap.TRY_REPO_MAPPING.get(repo_name)
    if not mapping_repo:
        error = f"Unable to lookup commits from {try_repo_scm_type} to {repo_scm_type}. {repo_name} is not supported."
        logger.info(error)
        raise ValueError(error)
    return mapping_repo


def get_commit_hash(
    mapping_repo: str, target_commit_hash: str, repo_scm_type: str
) -> str:
    """Return the equivalent commit hash in `repo_scm_type`, or raise `ValueError`."""
    try:
        if repo_scm_type == SCMType.HG:
            return CommitMap.git2hg(mapping_repo, target_commit_hash)
        return CommitMap.hg2git(mapping_repo, target_commit_hash)
    except CommitMap.DoesNotExist as exc:
        error = f"Could not determine the equivalent base commit for {target_commit_hash} in {repo_scm_type} for {mapping_repo}. Please try again later."
        logger.warning(error)
        raise ValueError(error) from exc


def resolve_target_commit_hash(
    patches_request: "PatchesRequest", mapping_repo_name: str, target_scm_type: str
) -> str:
    """Return the request's `base_commit` expressed in `target_scm_type`.

    Convert `base_commit` from `base_commit_vcs` to `target_scm_type` using the
    commit map registered for `mapping_repo_name`. Raise
    `BadRequestProblemException` when the map or the mapped commit is unavailable.
    """
    if patches_request.base_commit_vcs == target_scm_type:
        return patches_request.base_commit

    try:
        mapping_repo = get_commit_map(
            patches_request.base_commit_vcs, mapping_repo_name, target_scm_type
        )
    except ValueError as exc:
        raise BadRequestProblemException(
            title="CommitMap not found", detail=str(exc)
        ) from exc

    try:
        return get_commit_hash(
            mapping_repo, patches_request.base_commit, target_scm_type
        )
    except ValueError as exc:
        raise BadRequestProblemException(
            title="Error converting SCM commit IDs", detail=str(exc)
        ) from exc


def get_git_backing_repo(try_repo: Repo) -> Repo | None:
    """Return the Git backing repo for `try_repo`, or `None` when none applies.

    Logs a warning and returns `None` when a backing repo is expected but not
    configured, so the push degrades to an Hg-only landing rather than failing.
    """
    backing_name = GIT_BACKING_REPOS.get(try_repo.name)
    if not backing_name:
        return None

    try:
        return Repo.objects.get(name=backing_name)
    except Repo.DoesNotExist:
        logger.warning(
            f"Git backing repo {backing_name} for {try_repo.name} is not "
            "configured; creating an Hg-only Try push."
        )
        return None


def build_revisions_from_patch_helpers(patch_helpers: list) -> list[Revision]:
    """Build a fresh list of `Revision` objects from parsed patch helpers.

    Each landing job needs its own `Revision` objects, since landing records the
    final commit hash on the `Revision` itself.
    """
    revisions = []
    for patch_helper in patch_helpers:
        author_name, author_email = patch_helper.parse_author_information()
        revisions.append(
            Revision.new_from_patch(
                raw_diff=patch_helper.get_diff(),
                patch_data={
                    "author_name": author_name,
                    "author_email": author_email,
                    "commit_message": patch_helper.get_commit_description(),
                    "timestamp": patch_helper.get_timestamp(),
                },
            )
        )
    return revisions


def create_git_backing_reference_revision(
    git_job: LandingJob, requester_email: str
) -> Revision:
    """Build a `Revision` recording the paired Git backing push details.

    Adds a small JSON file on top of the Hg Try push referencing the Git backing
    job, so the two pushes can be correlated and CI knows which Git revision and
    branch to clone from. We add a new commit rather than rewriting the push's
    existing `try_task_config.json`, whose opaque diff cannot be reliably edited
    here.
    """
    contents = json.dumps(
        {
            "git_landing_job_id": git_job.id,
            "git_base_commit_hash": git_job.target_commit_hash,
            "git_branch": git_job.git_branch,
        },
        indent=2,
    )
    content_lines = contents.splitlines()
    diff_header_lines = [
        f"diff --git a/{GIT_BACKING_JOB_FILE} b/{GIT_BACKING_JOB_FILE}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{GIT_BACKING_JOB_FILE}",
        f"@@ -0,0 +1,{len(content_lines)} @@",
    ]
    added_lines = [f"+{line}" for line in content_lines]
    raw_diff = "\n".join(diff_header_lines + added_lines) + "\n"

    return Revision.new_from_patch(
        raw_diff=raw_diff,
        patch_data={
            "author_name": "Lando",
            "author_email": requester_email,
            "commit_message": f"Add reference to Git backing landing job {git_job.id}",
            "timestamp": str(int(time.time())),
        },
    )


def create_git_backing_job(
    patches_request: "PatchesRequest",
    try_repo: Repo,
    git_backing_repo: Repo,
    patch_helpers: list,
    requester_email: str,
) -> LandingJob:
    """Create the Git backing `LandingJob` for a Try push.

    Lands the push's patches on a per-push branch of the backing repo so pushes
    don't collide on its default branch.
    """
    target_commit_hash = resolve_target_commit_hash(
        patches_request, try_repo.name, git_backing_repo.scm_type
    )
    git_job = LandingJob.objects.create(
        target_repo=git_backing_repo,
        requester_email=requester_email,
        target_commit_hash=target_commit_hash,
        status=JobStatus.SUBMITTED,
    )
    git_job.git_branch = f"try-push-{git_job.id}"

    revisions = build_revisions_from_patch_helpers(patch_helpers)
    add_revisions_to_job(revisions, git_job)
    git_job.save()
    return git_job


def create_try_landing_job(
    try_repo: Repo,
    target_commit_hash: str,
    patch_helpers: list,
    requester_email: str,
    git_job: LandingJob | None,
) -> LandingJob:
    """Create the Hg Try `LandingJob`, referencing the paired Git backing job.

    When `git_job` is set, a reference revision recording its ID is added on top
    of the push.
    """
    try_job = LandingJob.objects.create(
        target_repo=try_repo,
        requester_email=requester_email,
        target_commit_hash=target_commit_hash,
        status=JobStatus.SUBMITTED,
    )

    revisions = build_revisions_from_patch_helpers(patch_helpers)
    if git_job:
        revisions.append(
            create_git_backing_reference_revision(git_job, requester_email)
        )
    add_revisions_to_job(revisions, try_job)
    try_job.save()
    return try_job


class PatchesRequest(Schema):
    """Provide the content of the push for submission to Lando."""

    repo_name: Annotated[
        str,
        Field(description="The Try repository to push to, defaults to `try`"),
    ] = "try"

    base_commit: Annotated[
        str,
        Field(
            description="The published base commit on which to apply `patches`",
        ),
        StringConstraints(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$"),
    ]
    base_commit_vcs: Annotated[
        SCMType,
        Field(
            description="The SCM that the `base_commit` hash is based on. Default is `hg`.",
            default=SCMType.HG,
        ),
    ]
    patches: Annotated[
        list[Base64Patch],
        Field(
            description="Ordered array of base64 encoded patches for submission to Lando."
        ),
    ]
    patch_format: Annotated[
        PatchFormat,
        Field(
            description="The format of the encoded patches in `patches`. Either `hgexport` or `git-format-patch` are accepted."
        ),
    ]


class JobResponse(Schema):
    """Response schema for a job submission."""

    id: Annotated[
        int, Field(description="The ID of the job created for this submission.")
    ]


@api.post(
    "/patches",
    summary="Submit a new landing job to the provided try repo.",
    url_name="api-patches",
    response={201: JobResponse, 400: ProblemDetail},
    openapi_extra={
        "responses": {
            200: {
                # XXX: This should not happen, but NinjaAPI doesn't let us disable this.
                "description": "Not used.",
                "content": None,
            },
            201: {
                "description": "Push was submitted successfully.",
                "content": {"application/json": {"schema": JobResponse.schema()}},
            },
            400: {
                "description": "Invalid request.",
                "content": {
                    "application/problem+json": {"schema": ProblemDetail.schema()}
                },
            },
        }
    },
)
def patches(
    request: WSGIRequest, patches_request: PatchesRequest
) -> tuple[int, Schema]:
    """Submit a new landing job to the provided try repo."""
    # Get the repo object.
    repo_name = patches_request.repo_name
    try:
        repo = Repo.objects.get(name=repo_name)
    except Repo.DoesNotExist:
        status = 400
        error = f"Repo {repo_name} does not exist."
        logger.info(
            error,
        )
        return status, ProblemDetail(
            title="Repository not found", detail=error, status=status
        )

    if not repo.is_try:
        status = 400
        error = f"Repo {repo_name} is not a Try repository."
        logger.info(
            error,
        )
        return status, ProblemDetail(
            title="Not a Try repository", detail=error, status=status
        )

    if not repo.user_can_push(request.user):
        raise PermissionDenied(f"Missing permissions: {repo.required_permission}")

    target_commit_hash = resolve_target_commit_hash(
        patches_request, repo.name, repo.scm_type
    )

    # Create PatchHelpers and run the checks prior to creating any DB object.
    patch_helper_class = PATCH_HELPER_MAPPING[patches_request.patch_format]
    patch_helpers = []
    for patch_no, patch_data in enumerate(patches_request.patches):
        # Decode the base64 patch data to bytes
        try:
            decoded_patch_bytes = base64.b64decode(patch_data)
        except binascii.Error as exc:
            raise BadRequestProblemException(
                title="Invalid base64 patch data",
                detail=f"Invalid base64 data for patch {patch_no}",
            ) from exc

        # Create PatchHelper instance to parse the patch.
        patch_io = io.BytesIO(decoded_patch_bytes)
        try:
            patch_helper = patch_helper_class.from_bytes_io(patch_io)

            # Validate that the author and timestamp metadata parse.
            patch_helper.parse_author_information()
            patch_helper.get_timestamp()
        except ValueError as exc:
            raise BadRequestProblemException(
                title="Invalid patch data",
                detail=f"Invalid patch data for patch {patch_no}",
            ) from exc

        patch_helpers.append(patch_helper)

    landing_checks = LandingChecks(request.user.email, repo.name)
    errors = landing_checks.run(
        repo.hooks,
        patch_helpers,
    )

    if errors:
        bulleted_errors = "\n  - ".join(errors)
        error_message = f"Patch failed checks:\n\n  - {bulleted_errors}"
        raise BadRequestProblemException(
            title="Errors found in pre-submission patch checks.",
            detail=error_message,
        )

    # A Try push lands on both a Git backing repo and the Hg Try repo during the
    # migration. We create the Git job first, then reference it from the Hg job.
    git_backing_repo = get_git_backing_repo(repo)

    # We are in a transaction, so jobs can be marked SUBMITTED directly rather
    # than following a two-step process starting with CREATED.
    with transaction.atomic():
        git_job = (
            create_git_backing_job(
                patches_request,
                repo,
                git_backing_repo,
                patch_helpers,
                request.user.email,
            )
            if git_backing_repo
            else None
        )

        try_job = create_try_landing_job(
            repo,
            target_commit_hash,
            patch_helpers,
            request.user.email,
            git_job,
        )

    return 201, JobResponse(
        id=try_job.id,
    )


#
# Mapping from legacy API paths.
#

legacy_api = NinjaAPI(auth=AccessTokenAuth(), urls_namespace="legacy-try")


@legacy_api.post(
    "/patches",
    deprecated=True,
    summary="Backward-compatible redirection to /try/api/patches.",
)
def redirect_to_api_patches(request: WSGIRequest) -> HttpResponsePermanentRedirect:
    return redirect("try:api-patches", permanent=True, preserve_request=True)
