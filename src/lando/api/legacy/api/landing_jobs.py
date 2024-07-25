import logging

from django.http import HttpRequest

from lando.main.auth import require_authenticated_user
from lando.main.models.landing_job import LandingJob, LandingJobAction, LandingJobStatus
from lando.main.support import ProblemException

logger = logging.getLogger(__name__)


@require_authenticated_user
def put(request: HttpRequest, landing_job_id: str, data: dict):
    """Update a landing job.

    Checks whether the logged in user is allowed to modify the landing job that is
    passed, does some basic validation on the data passed, and updates the landing job
    instance accordingly.

    Args:
        landing_job_id (str): The unique ID of the LandingJob object.
        data (dict): A dictionary containing the cleaned data payload from the request.

    Raises:
        ProblemException: If a LandingJob object corresponding to the landing_job_id
            is not found, if a user is not authorized to access said LandingJob object,
            if an invalid status is provided, or if a LandingJob object can not be
            updated (for example, when trying to cancel a job that is already in
            progress).
    """
    with LandingJob.lock_table:
        landing_job = LandingJob.objects.get(pk=landing_job_id)

    if not landing_job:
        raise ProblemException(
            404,
            "Landing job not found",
            f"A landing job with ID {landing_job_id} was not found.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    ldap_username = request.user.email
    if landing_job.requester_email != ldap_username:
        raise ProblemException(
            403,
            "Unauthorized",
            f"User not authorized to update landing job {landing_job_id}",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403",
        )

    # TODO: fix this. See bug 1893455.
    if data["status"] != "CANCELLED":
        raise ProblemException(
            400,
            "Invalid status provided",
            f"The provided status {data['status']} is not allowed.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if landing_job.status in (LandingJobStatus.SUBMITTED, LandingJobStatus.DEFERRED):
        landing_job.transition_status(LandingJobAction.CANCEL)
        landing_job.save()
        return {"id": landing_job.id}, 200
    else:
        raise ProblemException(
            400,
            "Landing job could not be cancelled.",
            f"Landing job status ({landing_job.status}) does not allow cancelling.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
