import base64
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
from lando.main.models.landing_job import LandingJob
from lando.main.models.profile import SCM_LEVEL_1
from lando.main.models.revision import Revision
from lando.main.scm.consts import SCMType
from lando.main.scm.helpers import PATCH_HELPER_MAPPING, PatchFormat
from lando.utils.auth import AccessTokenAuth, PermissionAccessTokenAuth
from lando.utils.exceptions import (
    BadRequestProblemException,
    ForbiddenProblemException,
    ProblemDetail,
    ProblemException,
    problem_exception_handler,
)

logger = logging.getLogger(__name__)

api = NinjaAPI(auth=PermissionAccessTokenAuth(SCM_LEVEL_1), urls_namespace="try")


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

    repo: Annotated[
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
            description="The VCS that the `base_commit` hash is based on. Default is `hg`.",
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
                # XXX: This should not happen, but NinjaAPI does't let me disable this.
                "description": "Not used.",
                "content": None,
            },
            201: {"description": "Push was submitted successfully."},
            400: {
                "description": "Invalid request.",
                "content": {
                    "application/problem+json": {"schema": ProblemDetail.schema()}
                },
            },
        }
    },
)
def patches(request: WSGIRequest, patches: PatchesRequest) -> tuple[int, Schema]:
    """Submit a set of patches to the Try server."""
    # Get the repo object.
    repo_name = patches.repo
    try:
        repo = Repo.objects.get(name=repo_name)
    except Repo.DoesNotExist:
        status = 404
        error = f"Repo {repo_name} does not exist."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth},
        )
        return status, ProblemDetail(
            title="Repository not found", detail=error, status=status
        )

    if not repo.is_try:
        status = 400
        error = f"Repo {repo_name} is not a Try repository."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth},
        )
        return status, ProblemDetail(
            title="Not a Try repository", detail=error, status=status
        )

    # XXX: We'll need a more flexible way to set this.
    mapping_repo = "firefox"

    target_commit_hash = patches.base_commit
    if patches.base_commit_vcs != repo.scm_type:
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
                extra={"user": request.user.email},
            )
            return status, ProblemDetail(
                title="Error converting VCS commit IDs",
                detail=f"Could not determine the equivalent base commit for {target_commit_hash} in {repo.scm_type} for {mapping_repo}. Please try again later.",
                status=status,
            )

    try_job = LandingJob.objects.create(
        target_repo=repo,
        requester_email=request.user.email,
        target_commit_hash=target_commit_hash,
        status=JobStatus.CREATED,
        priority=-10,
    )

    # Create Revision objects from patches and associate them with the job
    revisions = []
    patch_helper_class = PATCH_HELPER_MAPPING[patches.patch_format]

    for patch_no, patch_data in enumerate(patches.patches):
        # Decode the base64 patch data to bytes
        try:
            decoded_patch_bytes = base64.b64decode(patch_data)
        except Exception as exc:
            raise BadRequestProblemException(
                title="Invalid base64 patch data",
                detail=f"Invalid base64 data for patch {patch_no}: {exc}",
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
                detail=f"Invalid patch data for patch {patch_no}: {exc}",
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

    try_job.add_revisions(revisions)
    try_job.sort_revisions(revisions)

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
