import base64
import enum
import io
import logging
from typing import Annotated

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponsePermanentRedirect, JsonResponse
from django.shortcuts import redirect
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from pydantic import Field, StringConstraints

from lando.main.auth import require_authenticated_user, require_permission
from lando.main.models import Repo
from lando.main.models.jobs import JobStatus
from lando.main.models.landing_job import LandingJob
from lando.main.models.profile import SCM_LEVEL_1
from lando.main.models.revision import Revision
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.scm.helpers import PATCH_HELPER_MAPPING, PatchFormat
from lando.try_api.models.job import TryJob
from lando.utils.auth import AccessTokenAuth
from lando.utils.exceptions import ProblemDetail

logger = logging.getLogger(__name__)

api = NinjaAPI(urls_namespace="try")


@api.get("/__userinfo__", auth=AccessTokenAuth())
def userinfo(request: WSGIRequest) -> JsonResponse:
    """Test endpoint to check token verification.

    Only available in non-prod environments."""
    if not settings.ENVIRONMENT.is_lower:
        raise HttpError(404, "Not Found")
    return JsonResponse({"user_id": str(request.auth)})


@enum.unique
class SCMType(str, enum.Enum):
    """Enumeration of acceptable VCS types."""

    GIT = SCM_TYPE_GIT
    HG = SCM_TYPE_HG


Base64Patch = Annotated[
    str, Field(description="Base64 encoded patch.", pattern=r"^[A-Za-z0-9+/]+={0,2}$")
]


class PatchesRequest(Schema):
    """Provide the content of the push for submission to Lando."""

    repo: Annotated[
        str,
        Field(description="The Try repository to push to, defaults to `firefox-try`"),
    ] = "firefox-try"

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


@require_authenticated_user
@require_permission(SCM_LEVEL_1)
@api.post(
    "/api/patches",
    summary="Submit a set of patches to the Try server.",
    url_name="api-patches",
    response={201: JobResponse, 400: ProblemDetail, 404: ProblemDetail},
    openapi_extra={
        "responses": {
            200: {
                # XXX: This should not happen, but NinjaAPI does't let me disable this.
                "description": "Not used.",
                "content": {},
            },
            201: {"description": "Push was submitted successfully."},
            400: {
                "description": "Invalid request.",
                # "content": {"application/problem+json": {"schema": ProblemDetail}},
            },
            404: {
                "description": "Repository not found.",
                # "content": {"application/problem+json": {"schema": ProblemDetail}},
            },
        }
    },
    auth=AccessTokenAuth(),
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

    if not repo.try_enabled:
        status = 400
        error = f"Repo {repo_name} is not a Try repository."
        logger.info(
            error,
            extra={"user": request.user.email, "token": request.auth},
        )
        return status, ProblemDetail(
            title="Not a Try repository", detail=error, status=status
        )

    try_job = TryJob.objects.create(
        target_repo=repo,
        requester_email=request.user.email,
        target_commit_hash=target_commit_hash,
        status=JobStatus.SUBMITTED,
        priority=-10,
    )

    # Create Revision objects from patches and associate them with the job
    revisions = []
    patch_helper_class = PATCH_HELPER_MAPPING[patches.patch_format]

    for patch_data in patches.patches:
        # Decode the base64 patch data to bytes
        decoded_patch_bytes = base64.b64decode(patch_data)

        # Create PatchHelper instance to parse the patch
        patch_io = io.BytesIO(decoded_patch_bytes)
        patch_helper = patch_helper_class.from_bytes_io(patch_io)

        # Extract patch information using PatchHelper
        author_name, author_email = patch_helper.parse_author_information()
        commit_message = patch_helper.get_commit_description()
        timestamp = patch_helper.get_timestamp()
        diff = patch_helper.get_diff()

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

    return 201, JobResponse(
        id=try_job.id,
    )


@api.post(
    "/patches",
    deprecated=True,
    summary="Backward-compatible redirection to /try/api/patches.",
)
def redirect_to_api_patches(request: WSGIRequest) -> HttpResponsePermanentRedirect:
    return redirect("try:api-patches", permanent=True, preserve_request=True)


@api.get("/api/jobs/{int:try_job_id}/", url_name="api-job")
def get_job_json(request: WSGIRequest, try_job_id: int) -> JsonResponse:
    job = LandingJob.objects.get(id=try_job_id)
    return JsonResponse(job.to_dict())
