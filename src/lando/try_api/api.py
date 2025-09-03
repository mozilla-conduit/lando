import enum
import logging
from typing import Annotated

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from pydantic import Field, StringConstraints

from lando.headless_api.api import AutomationOperation, post_repo_actions
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.utils.auth import AccessTokenAuth

logger = logging.getLogger(__name__)

api = NinjaAPI(urls_namespace="try", auth=AccessTokenAuth())


@api.get("/__userinfo__")
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


@enum.unique
class PatchFormat(str, enum.Enum):
    """Enumeration of acceptable patch formats."""

    GIT_FORMAT_PATCH = "git-format-patch"
    HGEXPORT = "hgexport"


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

    headless_request: AutomationOperation


@api.post(
    "/patches",
    summary="Submit a set of patches to the Try server.",
    response={201: JobResponse},
    openapi_extra={
        "responses": {
            200: {
                # XXX: This should not happen, but NinjaAPI does't let me disable this.
                "description": "Not used.",
                "content": {},
            },
            201: {"description": "Push was submitted successfully."},
        }
    },
)
def patches(request: WSGIRequest, patches: PatchesRequest) -> tuple[int, Schema]:
    """Submit a set of patches to the Try server."""

    actions = [
        {
            "action": "add-commit-base64",
            "content": patch,
            # XXX: limitations:
            # * data.base_commit_vcs = "git"
            # * data.patch_format = "git-format-patch
        }
        for patch in patches.patches
    ]

    headless_request = {
        "actions": actions,
        "relbranch": {
            "branch_name": "",
            "commit_sha": patches.base_commit,
        },
    }

    _, automation_job = post_repo_actions(
        request,
        repo_name=patches.repo,  # XXX:  make sure we validate and authenticate!
        operation=AutomationOperation(**headless_request),
    )

    return 201, JobResponse(
        id=automation_job["id"],
        headless_request=headless_request,
        automation_job=automation_job,
    )
