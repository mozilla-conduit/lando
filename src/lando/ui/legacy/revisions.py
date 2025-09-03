import json
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator

from lando.api.legacy import api as legacy_api
from lando.api.legacy.uplift import MAX_UPLIFT_STACK_SIZE
from lando.api.legacy.validation import revision_id_to_int
from lando.main.auth import force_auth_refresh, require_phabricator_api_key
from lando.main.models import Repo
from lando.main.models.uplift import UpliftAssessment, UpliftRevision
from lando.ui.legacy.forms import (
    TransplantRequestForm,
    UpliftAssessmentEditForm,
    UpliftRequestForm,
)
from lando.ui.legacy.stacks import Edge, draw_stack_graph, sort_stack_topological
from lando.ui.views import LandoView
from lando.utils.tasks import set_uplift_request_form_on_revision

logger = logging.getLogger(__name__)

# TODO: port this hook once lando-api is merged and hooks are implemented.
# revisions.before_request(set_last_local_referrer)


class Uplift(LandoView):
    @force_auth_refresh
    def post(self, request: WSGIRequest) -> HttpResponse:
        """Process the uplift request submission."""
        uplift_request_form = UpliftRequestForm(request.POST)

        if not request.user.is_authenticated:
            raise PermissionDenied()

        if not uplift_request_form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in uplift_request_form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            # Not ideal, but because we do not have access to the revision ID
            # we will just redirect the user back to the referring page and
            # they will see the flash messages.
            return redirect(request.META.get("HTTP_REFERER"))

        revision_id = revision_id_to_int(
            uplift_request_form.cleaned_data["revision_id"]
        )
        repository = uplift_request_form.cleaned_data["repository"]

        # Create DB rows for the uplift submission.
        with transaction.atomic():
            assessment = UpliftAssessment.from_cleaned_form(
                request.user, uplift_request_form.cleaned_data
            )

            response = legacy_api.uplift.create(
                request,
                data={
                    "revision_id": revision_id,
                    "repository": repository,
                    "assessment_str": (assessment.to_conduit_json_str()),
                },
            )

            tip_revision_id = response["tip_differential"]["revision_id"]

            UpliftRevision.objects.create(
                assessment=assessment,
                revision_id=tip_revision_id,
            )

        # Redirect to the tip revision's URL.
        tip_differential = response["tip_differential"]["url"]
        return redirect(tip_differential)


class UpliftAssessmentEditView(LandoView):
    """Update and create uplift request assessment forms."""

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=False))
    def post(self, request: WSGIRequest) -> HttpResponse:
        """Update an uplift request assessment."""
        uplift_assessment_form = UpliftAssessmentEditForm(request.POST)

        if not uplift_assessment_form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in uplift_assessment_form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            return redirect(request.META.get("HTTP_REFERER"))

        revision_id = revision_id_to_int(
            uplift_assessment_form.cleaned_data["revision_id"]
        )

        try:
            uplift_revision = UpliftRevision.objects.get(revision_id=revision_id)
        except UpliftRevision.DoesNotExist:
            # No existing assessment for this revision, so we create one.
            with transaction.atomic():
                assessment = UpliftAssessment.from_cleaned_form(
                    cleaned_data=uplift_assessment_form.cleaned_data,
                    user=request.user,
                )
                UpliftRevision.objects.create(
                    assessment=assessment,
                    revision_id=revision_id,
                )

            messages.add_message(
                request, messages.SUCCESS, "Uplift assessment created."
            )
        else:
            old_assessment = uplift_revision.assessment

            revisions = old_assessment.revisions.all()

            # Store uplift request assessment response.
            with transaction.atomic():
                assessment = UpliftAssessment.from_cleaned_form(
                    cleaned_data=uplift_assessment_form.cleaned_data,
                    user=request.user,
                )

                for revision in revisions:
                    revision.assessment = assessment
                    revision.save()

                old_assessment.delete()

            messages.add_message(request, messages.SUCCESS, "Uplift assessment saved.")

        # Trigger a Celery task to update the form on Phabricator.
        set_uplift_request_form_on_revision.apply_async(
            args=(
                revision_id,
                assessment.to_conduit_json_str(),
                request.user.profile.phabricator_api_key,
            )
        )

        return redirect(request.META.get("HTTP_REFERER"))


class Revision(LandoView):
    def get(
        self, request: WSGIRequest, revision_id: int, *args, **kwargs
    ) -> TemplateResponse:
        lando_user = request.user

        # This is added for backwards compatibility.
        stack = legacy_api.stacks.get(request, revision_id)

        form = TransplantRequestForm()
        errors = []

        uplift_request_form = UpliftRequestForm()
        uplift_request_form.fields["revision_id"].initial = f"D{revision_id}"

        # Build a mapping from phid to revision and identify
        # the data for the revision used to load this page.

        revision_phid = None
        revisions = {}
        for r in stack["revisions"]:
            revisions[r["phid"]] = r
            if r["id"] == "D{}".format(revision_id):
                revision_phid = r["phid"]

        # Build a mapping from phid to repository.
        repositories = {}
        for phab_repo in stack["repositories"]:
            repositories[phab_repo["phid"]] = Repo.objects.get(
                short_name=phab_repo["short_name"]
            )

        # Request all previous landing jobs for the stack.
        landing_jobs = legacy_api.transplants.get_list(request, f"D{revision_id}")

        # The revision may appear in many `landable_paths`` if it has
        # multiple children, or any of its landable descendents have
        # multiple children. That being said, there should only be a
        # single unique path up to this revision, so find the first
        # it appears in. The revisions up to the target one in this
        # path form the landable series.
        #
        # We also form a set of all the revisions that are landable
        # so we can present selection for what to land.
        series = None
        landable = set()
        for p in stack["landable_paths"]:
            for phid in p:
                landable.add(phid)

            try:
                series = p[: p.index(revision_phid) + 1]
            except ValueError:
                pass

        dryrun = None
        target_repo = None
        if series and lando_user.is_authenticated:
            landing_path = [
                {
                    "revision_id": revisions[phid]["id"],
                    "diff_id": revisions[phid]["diff"]["id"],
                }
                for phid in series
            ]
            landing_path_json = json.dumps(landing_path)
            form.fields["landing_path"].initial = landing_path_json

            dryrun = legacy_api.transplants.dryrun(
                request, data={"landing_path": landing_path}
            )
            form.fields["confirmation_token"].initial = dryrun["confirmation_token"]
            series = list(reversed(series))
            revision_repo = repositories.get(revisions[series[0]]["repo_phid"])
            target_repo = (
                revision_repo
                if not revision_repo.is_legacy
                else revision_repo.new_target
            )

        phids = set(revisions.keys())
        edges = {Edge(child=e[0], parent=e[1]) for e in stack["edges"]}
        order = sort_stack_topological(
            phids, edges, key=lambda x: int(revisions[x]["id"][1:])
        )
        drawing_width, drawing_rows = draw_stack_graph(phids, edges, order)

        # Get the `Repo` object for the current revision.
        revision = revisions[revision_phid]
        revision_repo = repositories.get(revision["repo_phid"])

        # Look for an existing `UpliftRevision` for this revision.
        try:
            uplift_revision = UpliftRevision.objects.get(revision_id=revision_id)
        except UpliftRevision.DoesNotExist:
            uplift_revision = None

        if revision_repo and revision_repo.approval_required and uplift_revision:
            # If an existing form is present, pre-populate the edit form.
            assessment = uplift_revision.assessment
            uplift_assessment_initial = assessment.to_form_dict()
            uplift_assessment_initial["revision_id"] = f"D{revision_id}"
            uplift_assessment_edit_form = UpliftAssessmentEditForm(
                initial=uplift_assessment_initial
            )
        else:
            # Use an empty edit form with `revision_id` pre-populated.
            uplift_assessment_edit_form = UpliftAssessmentEditForm(
                initial={"revision_id": f"D{revision_id}"}
            )

        # Current implementation requires that all commits have the flags appended.
        # This may change in the future. What we do here is:
        # - if all commits have the flag, then disable the checkbox
        # - if any commits do not have the flag, then enable the checkbox

        if target_repo:
            existing_flags = {f[0]: False for f in target_repo.commit_flags}
            for flag in existing_flags:
                existing_flags[flag] = all(
                    flag in r["commit_message"] for r in revisions.values()
                )

        else:
            existing_flags = {}

        # Check if the stack is larger than our maximum upliftable stack size.
        uplift_stack_too_large = series and len(series) > MAX_UPLIFT_STACK_SIZE

        context = {
            "revision_id": "D{}".format(revision_id),
            "series": series,
            "landable": landable,
            "dryrun": dryrun,
            "stack": stack,
            "rows": list(zip(reversed(order), reversed(drawing_rows), strict=False)),
            "drawing_width": drawing_width,
            "landing_jobs": landing_jobs,
            "revisions": revisions,
            "revision_phid": revision_phid,
            "revision_repo": revision_repo,
            "target_repo": target_repo,
            "errors": errors,
            "form": form,
            "flags": target_repo.commit_flags if target_repo else [],
            "existing_flags": existing_flags,
            "uplift_request_form": uplift_request_form,
            "uplift_assessment_form": uplift_assessment_edit_form,
            "uplift_stack_too_large": uplift_stack_too_large,
            "max_uplift_stack_size": MAX_UPLIFT_STACK_SIZE,
        }

        return TemplateResponse(
            request=request,
            template="stack/stack.html",
            context=context,
        )

    @force_auth_refresh
    def post(
        self, request: WSGIRequest, revision_id: int, *args, **kwargs
    ) -> HttpResponseRedirect:
        form = TransplantRequestForm(request.POST)
        errors = []

        if not request.user.is_authenticated:
            errors.append("You must be logged in to request a landing")

        if form.is_valid() and not errors:
            form.cleaned_data["landing_path"] = json.loads(
                form.cleaned_data["landing_path"]
            )
            form.cleaned_data["flags"] = (
                form.cleaned_data["flags"] if form.cleaned_data["flags"] else []
            )
            legacy_api.transplants.post(request, data=form.cleaned_data)
            # We don't actually need any of the data from the
            # the submission. As long as an exception wasn't
            # raised we're successful.
            return redirect("revisions-page", revision_id=revision_id)

        if form.errors:
            errors += [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in form.errors.items()
            ]

        for error in errors:
            messages.add_message(request, messages.ERROR, error)
        return redirect("revisions-page", revision_id=revision_id)
