import logging

from django.http import Http404, HttpRequest, JsonResponse

from lando.main.auth import require_authenticated_user
from lando.main.models.landing_job import LandingJob, LandingJobAction, LandingJobStatus

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
        LegacyAPIException: If a LandingJob object corresponding to the landing_job_id
            is not found, if a user is not authorized to access said LandingJob object,
            if an invalid status is provided, or if a LandingJob object can not be
            updated (for example, when trying to cancel a job that is already in
            progress).
    """
    with LandingJob.lock_table:
        landing_job = LandingJob.objects.get(pk=landing_job_id)

    if not landing_job:
        raise Http404(f"A landing job with ID {landing_job_id} was not found.")

    ldap_username = request.user.email
    if landing_job.requester_email != ldap_username:
        raise PermissionError(
            f"User not authorized to update landing job {landing_job_id}"
        )

    # TODO: fix this. See bug 1893455.
    if data["status"] != "CANCELLED":
        data = {"errors": [f"The provided status {data['status']} is not allowed."]}
        return JsonResponse(data, status_code=400)

    if landing_job.status in (LandingJobStatus.SUBMITTED, LandingJobStatus.DEFERRED):
        landing_job.transition_status(LandingJobAction.CANCEL)
        landing_job.save()
        return {"id": landing_job.id}, 200
    else:
        data = {
            "errors": [
                f"Landing job status ({landing_job.status}) does not allow cancelling."
            ]
        }
        return JsonResponse(data, status_code=400)
