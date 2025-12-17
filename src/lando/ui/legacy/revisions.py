import json
import logging

from django.contrib import messages
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator

from lando.api.legacy import api as legacy_api
from lando.api.legacy.validation import parse_revision_ids
from lando.main.auth import force_auth_refresh, require_phabricator_api_key
from lando.main.models import Repo
from lando.main.models.jobs import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
)
from lando.ui.legacy.forms import (
    LinkUpliftAssessmentForm,
    TransplantRequestForm,
    UpliftAssessmentForm,
    UpliftAssessmentLinkForm,
    UpliftRequestForm,
)
from lando.ui.legacy.stacks import Edge, draw_stack_graph, sort_stack_topological
from lando.ui.uplift.context import UpliftContext
from lando.ui.views import LandoView
from lando.utils.tasks import set_uplift_request_form_on_revision

logger = logging.getLogger(__name__)


class UpliftRequestView(LandoView):
    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=False))
    def post(self, request: WSGIRequest) -> HttpResponse:
        """Process the uplift request submission."""
        uplift_request_form = UpliftRequestForm(request.POST)

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

        source_revisions = uplift_request_form.cleaned_data["source_revisions"]
        repositories = uplift_request_form.cleaned_data["repositories"]

        # Create DB rows for the uplift submission.
        with transaction.atomic():
            # Create the assessment form.
            assessment = uplift_request_form.save(commit=False)
            assessment.user = request.user
            assessment.save()

            # Create the `UpliftSubmission` to represent this
            # form submission and tie jobs together.
            uplift_request = UpliftSubmission.objects.create(
                requested_by=request.user,
                assessment=assessment,
                requested_revision_ids=[
                    revision.revision_id for revision in source_revisions
                ],
            )

            # Create `UpliftJob`s and associate with this request.
            for repo in repositories:
                job = UpliftJob.objects.create(
                    submission=uplift_request,
                    requester_email=request.user.email,
                    status=JobStatus.SUBMITTED,
                    target_repo=repo,
                )
                job.add_revisions(source_revisions)
                job.sort_revisions(source_revisions)
                job.save()

        messages.add_message(request, messages.SUCCESS, "Uplift request queued.")

        return redirect(request.META.get("HTTP_REFERER"))


class UpliftAssessmentCreateOrEditView(LandoView):
    """Update and create uplift request assessment forms."""

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=False))
    def post(self, request: WSGIRequest, revision_id: int) -> HttpResponse:
        """Update an uplift request assessment."""

        uplift_revision = UpliftRevision.one_or_none(revision_id=revision_id)
        existing_assessment = uplift_revision.assessment if uplift_revision else None

        uplift_assessment_form = UpliftAssessmentForm(
            request.POST,
            instance=existing_assessment,
        )

        if not uplift_assessment_form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in uplift_assessment_form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            return redirect(request.META.get("HTTP_REFERER"))

        with transaction.atomic():
            assessment = uplift_assessment_form.save(commit=False)
            assessment.user = request.user
            assessment.save()

            message = "Uplift assessment updated."
            if uplift_revision is None:
                logger.info(
                    f"No existing assessment for {revision_id=}, creating a new instance."
                )
                UpliftRevision.objects.create(
                    assessment=assessment,
                    revision_id=revision_id,
                )
                message = "Uplift assessment created."

        messages.add_message(request, messages.SUCCESS, message)

        # Trigger a Celery task to update the form on Phabricator.
        set_uplift_request_form_on_revision.apply_async(
            args=(
                revision_id,
                assessment.to_conduit_json_str(),
                request.user.id,
            )
        )

        return redirect(request.META.get("HTTP_REFERER"))


class UpliftAssessmentLinkView(LandoView):
    """Link an existing uplift assessment to a revision."""

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=False))
    def post(self, request: WSGIRequest, revision_id: int) -> HttpResponse:
        """Link an existing uplift assessment to this revision."""

        uplift_revision = UpliftRevision.one_or_none(revision_id=revision_id)
        existing_assessment = uplift_revision.assessment if uplift_revision else None

        link_form = LinkUpliftAssessmentForm(request.POST, user=request.user)

        if not link_form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in link_form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            return redirect(request.META.get("HTTP_REFERER"))

        assessment = link_form.cleaned_data["assessment"]

        with transaction.atomic():
            uplift_revision, created = UpliftRevision.objects.update_or_create(
                revision_id=revision_id,
                defaults={"assessment": assessment},
            )

        if existing_assessment and existing_assessment.pk == assessment.pk:
            messages.add_message(
                request,
                messages.INFO,
                "This revision is already linked to the selected assessment.",
            )
        else:
            set_uplift_request_form_on_revision.apply_async(
                args=(
                    revision_id,
                    assessment.to_conduit_json_str(),
                    request.user.id,
                )
            )

            if created or existing_assessment is None:
                message = "Linked existing assessment to this revision."
            else:
                message = "Replaced linked assessment for this revision."

            messages.add_message(request, messages.SUCCESS, message)

        return redirect(request.META.get("HTTP_REFERER"))


class UpliftAssessmentBatchLinkView(LandoView):
    """Create/update an assessment and link it to multiple revisions."""

    @force_auth_refresh
    def get(self, request: WSGIRequest) -> TemplateResponse:
        """Display the uplift assessment form for linking to multiple revisions."""
        if not request.user.is_authenticated:
            messages.add_message(
                request,
                messages.ERROR,
                "Must be logged in to submit an uplift assessment.",
            )
            return redirect("/")

        # Get the comma-separated list of revision IDs from the query parameters.
        revisions_str = request.GET.get("revisions", "")
        if not revisions_str:
            messages.add_message(
                request,
                messages.ERROR,
                "No revision IDs provided. Please specify the 'revisions' parameter.",
            )
            return redirect("/")

        # Validate the revision IDs format.
        try:
            revision_ids = parse_revision_ids(revisions_str)
        except ValueError as e:
            messages.add_message(
                request,
                messages.ERROR,
                str(e),
            )
            return redirect("/")

        # Check if we're updating an existing assessment.
        assessment_id = request.GET.get("assessment_id")
        assessment_instance = None

        if assessment_id:
            try:
                assessment_instance = UpliftAssessment.objects.get(
                    id=assessment_id,
                    user=request.user,
                )
            except (ValueError, UpliftAssessment.DoesNotExist):
                messages.add_message(
                    request,
                    messages.ERROR,
                    "Assessment not found or you don't have permission to edit it.",
                )
                return redirect("/")

        logger.info(
            f"Uplift assessment batch link GET: user={request.user.id}, "
            f"revisions={revision_ids}, assessment_id={assessment_id}"
        )

        # Create the form with the assessment instance if updating.
        initial_data = {"revision_ids": ",".join(revision_ids)}
        if assessment_instance:
            initial_data["assessment"] = assessment_instance

        assessment_form = UpliftAssessmentLinkForm(
            initial=initial_data,
            instance=assessment_instance,
            user=request.user,
        )

        # Get existing linked revisions if updating an assessment.
        existing_linked_revision_ids = []
        if assessment_instance:
            existing_linked_revision_ids = list(
                assessment_instance.revisions.values_list("revision_id", flat=True)
            )

        context = {
            "form": assessment_form,
            "revision_ids": revision_ids,
            "existing_linked_revision_ids": existing_linked_revision_ids,
            "is_update": assessment_instance is not None,
        }

        return TemplateResponse(
            request=request,
            template="uplift/request.html",
            context=context,
        )

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=False))
    def post(self, request: WSGIRequest) -> HttpResponse:
        """Handle form submission and link assessment to multiple revisions."""

        # Check if we're updating an existing assessment by checking POST data.
        # This allows us to load the instance before binding the form.
        assessment_instance = None
        assessment_id = request.POST.get("assessment")

        if assessment_id:
            try:
                assessment_instance = UpliftAssessment.objects.get(
                    id=int(assessment_id),
                    user=request.user,
                )
            except (ValueError, UpliftAssessment.DoesNotExist):
                messages.add_message(
                    request,
                    messages.ERROR,
                    "Assessment not found or you don't have permission to edit it.",
                )
                return redirect("/")

        # Bind the form to POST data with the instance (if updating).
        form = UpliftAssessmentLinkForm(
            request.POST,
            user=request.user,
            instance=assessment_instance,
        )

        if not form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            return redirect(request.META.get("HTTP_REFERER"))

        # Get cleaned data.
        revision_ids = form.cleaned_data["revision_ids"]

        logger.info(
            f"Uplift assessment batch link POST: user={request.user.id}, "
            f"revisions={revision_ids}, assessment_id={assessment_id}"
        )

        # Create or update assessment and link to revisions in a single transaction.
        with transaction.atomic():
            assessment = form.save(commit=False)
            assessment.user = request.user
            assessment.save()

            # Link assessment to all revisions.
            for revision_id in revision_ids:
                UpliftRevision.objects.update_or_create(
                    revision_id=revision_id,
                    defaults={"assessment": assessment},
                )

        # After successful database transaction, trigger Celery tasks to update Phabricator.
        for revision_id in revision_ids:
            set_uplift_request_form_on_revision.apply_async(
                args=(
                    revision_id,
                    assessment.to_conduit_json_str(),
                    request.user.id,
                )
            )

        # Success message.
        if assessment_instance:
            message = (
                f"Assessment updated and linked to {len(revision_ids)} revision(s)."
            )
        else:
            message = (
                f"Assessment created and linked to {len(revision_ids)} revision(s)."
            )

        messages.add_message(request, messages.SUCCESS, message)
        logger.info(message)

        # Redirect to the first revision.
        return redirect("revisions-page", revision_id=revision_ids[0])


class RevisionView(LandoView):
    def get(
        self, request: WSGIRequest, revision_id: int, *args, **kwargs
    ) -> TemplateResponse:
        lando_user = request.user

        # This is added for backwards compatibility.
        stack = legacy_api.stacks.get(request, revision_id)

        form = TransplantRequestForm()
        errors = []

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

        # Build the uplift templating context.
        uplift_context = UpliftContext.build(
            request=request,
            revision_id=revision_id,
            revision_phid=revision_phid,
            revision_repo=revision_repo,
            revisions=revisions,
            stack=stack["stack"],
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
            "uplift": uplift_context,
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
