import base64
import binascii
import io
import logging
from typing import Annotated

from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
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
from lando.utils.ninja_auth import AccessTokenAuth

logger = logging.getLogger(__name__)

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

    target_commit_hash = patches_request.base_commit
    if patches_request.base_commit_vcs != repo.scm_type:
        mapping_repo = CommitMap.TRY_REPO_MAPPING.get(repo.name)
        if not mapping_repo:
            status = 400
            error = f"Unable to lookup commits from {patches_request.base_commit_vcs} to {repo.scm_type}. {repo_name} is not supported."
            logger.info(
                error,
            )
            return status, ProblemDetail(
                title="CommitMap not found", detail=error, status=status
            )

        try:
            if repo.scm_type == SCMType.HG:
                target_commit_hash = CommitMap.git2hg(mapping_repo, target_commit_hash)
            else:
                target_commit_hash = CommitMap.hg2git(mapping_repo, target_commit_hash)
        except CommitMap.DoesNotExist:
            status = 400
            error = f"Could not determine the equivalent base commit for {target_commit_hash} in {repo.scm_type} for {mapping_repo}. Please try again later."
            logger.warning(
                error,
            )
            return status, ProblemDetail(
                title="Error converting SCM commit IDs",
                detail=error,
                status=status,
            )

    try_job = LandingJob.objects.create(
        target_repo=repo,
        requester_email=request.user.email,
        target_commit_hash=target_commit_hash,
        status=JobStatus.CREATED,
    )

    # Create Revision objects from patches and associate them with the job
    revisions = []
    patch_helper_class = PATCH_HELPER_MAPPING[patches_request.patch_format]

    for patch_no, patch_data in enumerate(patches_request.patches):
        # Decode the base64 patch data to bytes
        try:
            decoded_patch_bytes = base64.b64decode(patch_data)
        except binascii.Error as exc:
            raise BadRequestProblemException(
                title="Invalid base64 patch data",
                detail=f"Invalid base64 data for patch {patch_no}",
            ) from exc

        # Create PatchHelper instance to parse the patch
        patch_io = io.BytesIO(decoded_patch_bytes)
        try:
            patch_helper = patch_helper_class.from_bytes_io(patch_io)

            # Extract patch information using PatchHelper
            author_name, author_email = patch_helper.parse_author_information()
            commit_message = patch_helper.get_commit_description()
            timestamp = patch_helper.get_timestamp()
            diff = patch_helper.get_diff()
        except ValueError as exc:
            raise BadRequestProblemException(
                title="Invalid patch data",
                detail=f"Invalid patch data for patch {patch_no}",
            ) from exc

        revision = Revision.new_from_patch(
            raw_diff=diff,
            patch_data={
                "author_name": author_name,
                "author_email": author_email,
                "commit_message": commit_message,
                "timestamp": timestamp,
            },
        )
        revisions.append(revision)

    add_revisions_to_job(revisions, try_job)

    try_job.status = JobStatus.SUBMITTED
    try_job.save()

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
