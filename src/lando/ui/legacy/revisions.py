import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator

from lando.api.legacy.revisions import seed_revisions_from_phabricator
from lando.api.legacy.validation import parse_revision_ids
from lando.main.auth import force_auth_refresh, require_phabricator_api_key
from lando.main.models.jobs import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
)
from lando.ui.legacy.forms import (
    LinkUpliftAssessmentForm,
    UpliftAssessmentForm,
    UpliftAssessmentLinkForm,
    UpliftRequestForm,
)
from lando.ui.views import LandoView
from lando.utils.phabricator import PhabricatorClient
from lando.utils.tasks import set_uplift_request_form_on_revision

logger = logging.getLogger(__name__)


class UpliftRequestView(LandoView):
    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=True))
    def post(self, phab: PhabricatorClient, request: WSGIRequest) -> HttpResponse:
        """Process the uplift request submission."""
        try:
            seed_revisions_from_phabricator(
                phab, request.POST.getlist("source_revisions")
            )
        except ValueError as exc:
            messages.add_message(request, messages.ERROR, str(exc))
            return redirect(request.META.get("HTTP_REFERER"))

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
        target_selection_method = uplift_request_form.cleaned_data[
            "target_selection_method"
        ]

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
                target_selection_method=target_selection_method,
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
                UpliftRevision.link_revision_to_assessment(revision_id, assessment)
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
            uplift_revision, created = UpliftRevision.link_revision_to_assessment(
                revision_id, assessment
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

    @method_decorator(login_required)
    @force_auth_refresh
    def get(self, request: WSGIRequest) -> TemplateResponse:
        """Display the uplift assessment form for linking to multiple revisions."""
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
            except ValueError, UpliftAssessment.DoesNotExist:
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
        initial_data = {
            "revision_ids": ",".join(str(rev_id) for rev_id in revision_ids)
        }
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
            "assessment": assessment_instance,
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
            except ValueError, UpliftAssessment.DoesNotExist:
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
                UpliftRevision.link_revision_to_assessment(revision_id, assessment)

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
