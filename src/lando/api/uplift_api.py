import logging

from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from ninja import NinjaAPI, Schema
from ninja.responses import codes_4xx

from lando.main.models.uplift import UpliftAssessment, UpliftRevision
from lando.utils.exceptions import (
    NotFoundProblemException,
    ProblemDetail,
    ProblemException,
    problem_exception_handler,
)
from lando.utils.ninja_auth import PhabricatorTokenAuth
from lando.utils.tasks import set_uplift_request_form_on_revision

logger = logging.getLogger(__name__)

api = NinjaAPI(auth=PhabricatorTokenAuth(), urls_namespace="uplift-api")
api.exception_handler(ProblemException)(problem_exception_handler)


class LinkRevisionRequest(Schema):
    """Request body for linking a revision to an uplift assessment."""

    revision_id: int
    assessment_id: int


class LinkRevisionResponse(Schema):
    """Response body after successfully linking a revision to an assessment."""

    revision_id: int
    assessment_id: int
    created: bool


@api.post(
    "/assessments/link",
    response={201: LinkRevisionResponse, codes_4xx: ProblemDetail},
)
def link_revision_to_assessment(
    request: WSGIRequest,
    body: LinkRevisionRequest,
) -> tuple[int, dict]:
    """Link a Phabricator revision to an existing uplift assessment.

    This endpoint is intended for use by `moz-phab uplift` after the
    developer has manually resolved merge conflicts and submitted their
    revision. It creates an `UpliftRevision` record linking the new
    revision to the assessment, and triggers a Celery task to update
    the uplift request form on Phabricator.
    """
    logger.debug(
        "Received request to link revision %d to assessment %d.",
        body.revision_id,
        body.assessment_id,
    )

    try:
        assessment = UpliftAssessment.objects.get(id=body.assessment_id)
    except UpliftAssessment.DoesNotExist:
        detail = f"Assessment with id {body.assessment_id} does not exist."
        logger.warning(detail)
        raise NotFoundProblemException(title="Assessment not found", detail=detail)

    with transaction.atomic():
        uplift_revision, created = UpliftRevision.link_revision_to_assessment(
            body.revision_id, assessment
        )

    logger.info(
        "Linked revision %d to assessment %d (created=%s).",
        body.revision_id,
        body.assessment_id,
        created,
    )

    # Trigger the Celery task to update the uplift form on Phabricator.
    set_uplift_request_form_on_revision.apply_async(
        args=(
            body.revision_id,
            assessment.to_conduit_json_str(),
            assessment.user.id,
        )
    )

    return 201, LinkRevisionResponse(
        revision_id=body.revision_id,
        assessment_id=body.assessment_id,
        created=created,
    )
