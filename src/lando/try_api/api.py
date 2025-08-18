import enum
import logging
from typing import Annotated

from django.conf import settings
from django.contrib.auth.models import User
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import HttpBearer
from pydantic import Field, StringConstraints

from lando.main.auth import LandoOIDCAuthenticationBackend
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG

logger = logging.getLogger(__name__)


class GlobalAuth(HttpBearer):
    """Bearer token-based authenticator delegating verification to the OIDC backend."""

    def authenticate(self, request: WSGIRequest, token: str) -> User:
        """Forward the authenticate request to the LandoOIDCAuthenticationBackend."""
        # The token is extracted in the LandoOIDCAuthenticationBackend, so we don't need
        # to pass it. But we need to inherit from HttpBearer for Auth to work.
        oidc_auth = LandoOIDCAuthenticationBackend()
        return oidc_auth.authenticate(request)


api = NinjaAPI(urls_namespace="try", auth=GlobalAuth())


@api.get("/__userinfo__")
def userinfo(request: WSGIRequest) -> JsonResponse:
    """Test endpoint to check token verification.

    Only available in non-prod environments."""
    if not settings.ENVIRONMENT.is_lower():
        raise HttpError(404, "Not Found")
    return JsonResponse({"token": str(request.auth)})


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
def patches(request: WSGIRequest, data: PatchesRequest) -> JsonResponse:
    """Submit a set of patches to the Try server."""
    return 201, JobResponse(id=42)
