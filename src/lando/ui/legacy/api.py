import logging

from itertools import (
    chain,
)
from lando.ui.legacy.forms import (
    UpliftRequestForm,
)
from lando.ui.legacy.helpers import (
    is_user_authenticated,
)

from lando.ui.views import LandoView

from django.http import JsonResponse
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


LandoAPIError = None


def get_uplift_repos() -> list[tuple[str, str]]:
    """Return the set of uplift repositories as a list of `(name, value)` tuples."""
    # TODO: implement this after lando-api is ported.
    return


class Uplift(LandoView):
    def post(self, request):
        """Process the uplift request WTForms submission."""
        # TODO: auth optional.
        # TODO: fix up parts of this method that use Lando API after merge.

        uplift_request_form = UpliftRequestForm()

        # Get the list of available uplift repos and populate the form with it.
        uplift_request_form.repository.choices = get_uplift_repos()

        if not is_user_authenticated():
            return JsonResponse(
                {"errors":
                    ["You must be logged in to request an uplift"]}, status_code=401)

        if not uplift_request_form.validate():
            errors = list(chain(*uplift_request_form.errors.values()))
            return JsonResponse({"errors": errors}, status_code=400)

        revision_id = uplift_request_form.revision_id.data
        repository = uplift_request_form.repository.data

        try:
            response = {}
            # response = api.request(
            #     "POST",
            #     "uplift",
            #     require_auth0=True,
            #     json={
            #         "revision_id": revision_id,
            #         "repository": repository,
            #     },
            # )
        except LandoAPIError as e:
            if not e.detail:
                raise e

            return JsonResponse({"errors": [e.detail]}, status_code=e.status_code)

        # Redirect to the tip revision's URL.
        # TODO add js for auto-opening the uplift request Phabricator form.
        # See https://bugzilla.mozilla.org/show_bug.cgi?id=1810257.
        tip_differential = response["tip_differential"]["url"]
        return redirect(tip_differential)


class LandingJob(LandoView):
    def put(self, request, landing_job_id: int):
        if not is_user_authenticated():
            errors = ["You must be logged in to update a landing job."]
            return JsonResponse({"errors": errors}, status_code=401)

        try:
            data = {}
            # data = api.request(
            #     "PUT",
            #     f"landing_jobs/{landing_job_id}",
            #     require_auth0=True,
            #     json=request.get_json(),
            # )
        except LandoAPIError as e:
            return JsonResponse(e.response, status_code=e.response["status"])
        return JsonResponse(data)
