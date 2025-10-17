import json
import logging

from django import forms
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View

from lando.main.auth import require_authenticated_user
from lando.main.models import JobAction, JobStatus, LandingJob
from lando.utils.exceptions import NotFoundProblemException

logger = logging.getLogger(__name__)


class LandingJobForm(forms.Form):
    """Simple form to clean API endpoint fields."""

    # NOTE: this is here as a quick solution to safely check and clean user input,
    # however it will likely be deprecated in favour of a more universal solution
    # as part of bug 1870097.
    landing_job_id = forms.IntegerField()
    status = forms.CharField()


class LandingJobApiView(View):
    def get(self, request: WSGIRequest, job_id: int) -> JsonResponse:
        """Get a landing job description as JSON."""
        try:
            job = LandingJob.objects.get(id=job_id)
        except LandingJob.DoesNotExist:
            # We should raise the NotFoundProblemException from exc, but for
            # the time being, we format the response the exception ourselves,
            # as there's nothing doing it further up.
            exc = NotFoundProblemException(
                title="Landing job not found",
                detail=f"A landing job with ID {job_id} was not found.",
            )
            return JsonResponse(exc.to_response(), status=404)

        return JsonResponse(job.to_dict())

    @method_decorator(require_authenticated_user)
    def put(self, request: WSGIRequest, job_id: int) -> JsonResponse:
        """Update a landing job.

        Checks whether the logged in user is allowed to modify the landing job that is
        passed, does some basic validation on the data passed, and updates the landing job
        instance accordingly.

        Args:
            job_id (int): The unique ID of the LandingJob object.
            data (dict): A dictionary containing the cleaned data payload from the request.

        Raises:
            LegacyAPIException: If a LandingJob object corresponding to the job_id
                is not found, if a user is not authorized to access said LandingJob object,
                if an invalid status is provided, or if a LandingJob object can not be
                updated (for example, when trying to cancel a job that is already in
                progress).
        """
        data = json.loads(request.body)
        data["landing_job_id"] = job_id
        form = LandingJobForm(data)

        if not form.is_valid():
            data = {
                "errors": [
                    f"{field}: {', '.join(field_errors)}"
                    for field, field_errors in form.errors.items()
                ]
            }
            return JsonResponse(data, status=400)

        job_id = form.cleaned_data["landing_job_id"]
        status = form.cleaned_data["status"]

        with LandingJob.lock_table:
            try:
                landing_job = LandingJob.objects.get(pk=job_id)
            except LandingJob.DoesNotExist:
                return JsonResponse(
                    {"detail": f"A landing job with ID {job_id} was not found."},
                    status=404,
                )

        ldap_username = request.user.email
        if landing_job.requester_email != ldap_username:
            return JsonResponse(
                {"detail": f"User not authorized to update landing job {job_id}"},
                status=403,
            )

        if status != JobStatus.CANCELLED:
            data = {"errors": [f"The provided status {status} is not allowed."]}
            return JsonResponse(data, status=400)

        if landing_job.status in (JobStatus.SUBMITTED, JobStatus.DEFERRED):
            landing_job.transition_status(JobAction.CANCEL)
            landing_job.save()
            return JsonResponse({"id": landing_job.id})
        else:
            data = {
                "errors": [
                    f"Landing job status ({landing_job.status}) does not allow cancelling."
                ]
            }
            return JsonResponse(data, status=400)
