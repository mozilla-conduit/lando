import json
import logging

from django import forms
from django.http import Http404, HttpRequest, JsonResponse

from lando.main.auth import require_authenticated_user
from lando.main.models.landing_job import LandingJob, LandingJobAction, LandingJobStatus

logger = logging.getLogger(__name__)


class LandingJobForm(forms.Form):
    """Simple form to clean API endpoint fields."""

    # NOTE: this is here as a quick solution to safely check and clean user input,
    # however it will likely be deprecated in favour of a more universal solution
    # as part of bug 1870097.
    landing_job_id = forms.IntegerField()
    status = forms.CharField()


@require_authenticated_user
def put(request: HttpRequest, landing_job_id: int) -> JsonResponse:
    """Update a landing job.

    Checks whether the logged in user is allowed to modify the landing job that is
    passed, does some basic validation on the data passed, and updates the landing job
    instance accordingly.

    Args:
        landing_job_id (int): The unique ID of the LandingJob object.
        data (dict): A dictionary containing the cleaned data payload from the request.

    Raises:
        LegacyAPIException: If a LandingJob object corresponding to the landing_job_id
            is not found, if a user is not authorized to access said LandingJob object,
            if an invalid status is provided, or if a LandingJob object can not be
            updated (for example, when trying to cancel a job that is already in
            progress).
    """
    data = json.loads(request.body)
    data["landing_job_id"] = landing_job_id
    form = LandingJobForm(data)

    if not form.is_valid():
        data = {
            "errors": [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in form.errors.items()
            ]
        }
        return JsonResponse(data, status=400)

    landing_job_id = form.cleaned_data["landing_job_id"]
    status = form.cleaned_data["status"]

    with LandingJob.lock_table:
        try:
            landing_job = LandingJob.objects.get(pk=landing_job_id)
        except LandingJob.DoesNotExist:
            raise Http404(f"A landing job with ID {landing_job_id} was not found.")

    ldap_username = request.user.email
    if landing_job.requester_email != ldap_username:
        raise PermissionError(
            f"User not authorized to update landing job {landing_job_id}"
        )

    if status != "CANCELLED":
        data = {"errors": [f"The provided status {status} is not allowed."]}
        return JsonResponse(data, status=400)

    if landing_job.status in (LandingJobStatus.SUBMITTED, LandingJobStatus.DEFERRED):
        landing_job.transition_status(LandingJobAction.CANCEL)
        landing_job.save()
        return JsonResponse({"id": landing_job.id})
    else:
        data = {
            "errors": [
                f"Landing job status ({landing_job.status}) does not allow cancelling."
            ]
        }
        return JsonResponse(data, status=400)
