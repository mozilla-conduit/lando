import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator

from lando.api.legacy import api as legacy_api
from lando.api.legacy.revisions import (
    get_bug_id_for_revision,
    get_bug_id_for_stack_tips,
    seed_revisions_from_phabricator,
)
from lando.api.legacy.validation import parse_revision_ids
from lando.main.auth import force_auth_refresh, require_phabricator_api_key
from lando.main.models import Profile, Repo
from lando.main.models.jobs import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
)
from lando.main.support import get_revisions_with_disallowed_authors
from lando.treestatus.utils import get_tree_by_name
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
from lando.utils.phabricator import PhabricatorClient
from lando.utils.tasks import set_uplift_request_form_on_revision

logger = logging.getLogger(__name__)

MISSING_BUG_NUMBER_ERROR = (
    "Uplifts require a bug number. Set the bug number on this revision in "
    "Phabricator, then try again."
)


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

        # The tip revision is the one the request was made from, so its bug is
        # the bug the assessment covers.
        tip_revision_id = source_revisions[-1].revision_id
        bug_id = get_bug_id_for_revision(phab, tip_revision_id)

        if bug_id is None:
            messages.add_message(request, messages.ERROR, MISSING_BUG_NUMBER_ERROR)
            return redirect(request.META.get("HTTP_REFERER"))

        # Create DB rows for the uplift submission.
        with transaction.atomic():
            # Create the assessment form.
            assessment = uplift_request_form.save(commit=False)
            assessment.user = request.user
            assessment.bug_id = bug_id
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


class UpliftAssessmentView(LandoView):
    """Create an uplift assessment on a revision, or edit one it displays."""

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=True))
    def post(
        self,
        phab: PhabricatorClient,
        request: WSGIRequest,
        revision_id: int,
        assessment_id: int | None = None,
    ) -> HttpResponse:
        """Save the uplift assessment form, creating it when no ID was given."""
        bug_id = get_bug_id_for_revision(phab, revision_id)

        if bug_id is None:
            messages.add_message(request, messages.ERROR, MISSING_BUG_NUMBER_ERROR)
            return redirect(request.META.get("HTTP_REFERER"))

        assessment = None
        if assessment_id is not None:
            # Reading the revision from Phabricator proves the requester was
            # granted access to it, so any assessment that revision displays is
            # editable from its page. That set is what scopes the endpoint.
            assessment = (
                UpliftAssessment.visible_on_revision(bug_id, revision_id)
                .filter(id=assessment_id)
                .first()
            )

            if assessment is None:
                messages.add_message(
                    request,
                    messages.ERROR,
                    f"Uplift assessment #{assessment_id} is not shown on "
                    f"D{revision_id}.",
                )
                return redirect(request.META.get("HTTP_REFERER"))

        creating = assessment is None
        assessment_form = UpliftAssessmentForm(
            request.POST,
            instance=assessment or UpliftAssessment(user=request.user, bug_id=bug_id),
        )

        if not assessment_form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in assessment_form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            return redirect(request.META.get("HTTP_REFERER"))

        with transaction.atomic():
            assessment = assessment_form.save()

            if creating:
                logger.info(
                    "Created uplift assessment #%s for bug %s.", assessment.id, bug_id
                )
                UpliftRevision.link_revision_to_assessment(revision_id, assessment)

        messages.add_message(
            request,
            messages.SUCCESS,
            f"Uplift assessment #{assessment.id} "
            f"{'created' if creating else 'updated'}.",
        )

        refresh_linked_revisions(assessment, request)

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
    """Create or reuse an assessment and link it to the given revisions.

    `moz-phab` sends developers here after creating uplift revisions, and the
    assessment is filed under the bug shared by the selected stack tips.
    """

    @method_decorator(login_required)
    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=True, provide_client=True))
    def get(self, phab: PhabricatorClient, request: WSGIRequest) -> HttpResponse:
        """Display the bug's assessments and the form for these revisions."""
        resolved = self.resolve_revisions(phab, request, request.GET.get("revisions"))
        if resolved is None:
            return redirect("/")
        revision_ids, bug_id = resolved

        assessment_instance = None
        assessment_id = request.GET.get("assessment_id")

        if assessment_id:
            assessment_instance = self.selected_assessment(
                assessment_id, bug_id, request
            )
            if assessment_instance is None:
                return redirect("/")

        logger.info(
            f"Uplift assessment batch link GET: user={request.user.id}, "
            f"revisions={revision_ids}, bug={bug_id}, assessment_id={assessment_id}"
        )

        initial_data = {
            "revision_ids": ",".join(str(rev_id) for rev_id in revision_ids)
        }
        if assessment_instance:
            initial_data["assessment"] = assessment_instance

        assessment_form = UpliftAssessmentLinkForm(
            initial=initial_data,
            instance=assessment_instance,
            user=request.user,
            bug_id=bug_id,
        )

        existing_linked_revision_ids = []
        if assessment_instance:
            existing_linked_revision_ids = list(
                assessment_instance.revisions.values_list("revision_id", flat=True)
            )

        context = {
            "form": assessment_form,
            "revision_ids": revision_ids,
            "revisions_param": initial_data["revision_ids"],
            "bug_id": bug_id,
            "bug_assessments": list(UpliftAssessment.for_bug(bug_id)),
            "existing_linked_revision_ids": existing_linked_revision_ids,
            "assessment": assessment_instance,
        }

        return TemplateResponse(
            request=request,
            template="uplift/request.html",
            context=context,
        )

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=True))
    def post(self, phab: PhabricatorClient, request: WSGIRequest) -> HttpResponse:
        """Save the assessment, filing it under the bug, and link the revisions."""
        resolved = self.resolve_revisions(
            phab, request, request.POST.get("revision_ids")
        )
        if resolved is None:
            return redirect(request.META.get("HTTP_REFERER") or "/")
        revision_ids, bug_id = resolved

        assessment_instance = None
        assessment_id = request.POST.get("assessment")

        if assessment_id:
            assessment_instance = self.selected_assessment(
                assessment_id, bug_id, request
            )
            if assessment_instance is None:
                return redirect("/")

        form = UpliftAssessmentLinkForm(
            request.POST,
            user=request.user,
            bug_id=bug_id,
            instance=assessment_instance,
        )

        if not form.is_valid():
            errors = [
                f"{field}: {', '.join(field_errors)}"
                for field, field_errors in form.errors.items()
            ]

            for error in errors:
                messages.add_message(request, messages.ERROR, error)

            return redirect(request.META.get("HTTP_REFERER") or "/")

        logger.info(
            f"Uplift assessment batch link POST: user={request.user.id}, "
            f"revisions={revision_ids}, bug={bug_id}, assessment_id={assessment_id}"
        )

        with transaction.atomic():
            assessment = form.save(commit=False)

            # A reused assessment keeps its original author.
            if assessment_instance is None:
                assessment.user = request.user

            # New assessments, and the user's own from before `bug_id` existed,
            # are filed under the bug so the revision page groups them.
            if assessment.bug_id is None:
                assessment.bug_id = bug_id

            assessment.save()

            for revision_id in revision_ids:
                UpliftRevision.link_revision_to_assessment(revision_id, assessment)

        refresh_linked_revisions(assessment, request)

        if assessment_instance:
            message = f"Assessment linked to {len(revision_ids)} revision(s)."
        else:
            message = (
                f"Assessment created and linked to {len(revision_ids)} revision(s)."
            )

        messages.add_message(request, messages.SUCCESS, message)
        logger.info(message)

        return redirect("revisions-page", revision_id=revision_ids[0])

    @staticmethod
    def resolve_revisions(
        phab: PhabricatorClient, request: WSGIRequest, revision_ids: str | None
    ) -> tuple[list[int], int] | None:
        """Return the requested revision IDs and their bug, flashing why if invalid.

        The bug is resolved from Phabricator rather than trusted from the page,
        which also confirms the requester can see every revision being linked.
        """
        try:
            parsed_ids = parse_revision_ids(revision_ids or "")
            return parsed_ids, get_bug_id_for_stack_tips(phab, parsed_ids)
        except ValueError as exc:
            messages.add_message(request, messages.ERROR, str(exc))
            return None

    @staticmethod
    def selected_assessment(
        assessment_id: str, bug_id: int, request: WSGIRequest
    ) -> UpliftAssessment | None:
        """Return the assessment chosen for reuse, flashing an error if unusable."""
        try:
            return UpliftAssessment.selectable_for_bug(bug_id, request.user).get(
                id=int(assessment_id)
            )
        except ValueError, UpliftAssessment.DoesNotExist:
            messages.add_message(
                request,
                messages.ERROR,
                f"Assessment not found, or not filed against bug {bug_id}.",
            )
            return None


class UpliftAssessmentBatchLinkExistingView(LandoView):
    """Link the given revisions to an existing assessment without editing it.

    This is the batch page's one-click alternative to its form, for when the bug
    already has an assessment that describes these revisions.
    """

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=False, provide_client=True))
    def post(self, phab: PhabricatorClient, request: WSGIRequest) -> HttpResponse:
        """Link the revisions to the chosen assessment."""
        resolved = UpliftAssessmentBatchLinkView.resolve_revisions(
            phab, request, request.POST.get("revision_ids")
        )
        if resolved is None:
            return redirect(request.META.get("HTTP_REFERER") or "/")
        revision_ids, bug_id = resolved

        assessment = UpliftAssessmentBatchLinkView.selected_assessment(
            request.POST.get("assessment", ""), bug_id, request
        )
        if assessment is None:
            return redirect(request.META.get("HTTP_REFERER") or "/")

        logger.info(
            f"Uplift assessment batch link existing: user={request.user.id}, "
            f"revisions={revision_ids}, bug={bug_id}, assessment_id={assessment.id}"
        )

        with transaction.atomic():
            # As when reusing it through the form, the user's own assessment from
            # before `bug_id` existed is filed under the bug.
            if assessment.bug_id is None:
                assessment.bug_id = bug_id
                assessment.save()

            for revision_id in revision_ids:
                UpliftRevision.link_revision_to_assessment(revision_id, assessment)

        refresh_linked_revisions(assessment, request)

        messages.add_message(
            request,
            messages.SUCCESS,
            f"Assessment #{assessment.id} linked to {len(revision_ids)} revision(s).",
        )

        return redirect("revisions-page", revision_id=revision_ids[0])


def refresh_linked_revisions(assessment: UpliftAssessment, request: WSGIRequest):
    """Refresh the assessment's form on every revision carrying it.

    Each of them shows the old answers on Phabricator until it is refreshed.
    """
    linked_revision_ids = assessment.revisions.exclude(revision_id=None).values_list(
        "revision_id", flat=True
    )

    for linked_revision_id in linked_revision_ids:
        set_uplift_request_form_on_revision.apply_async(
            args=(
                linked_revision_id,
                assessment.to_conduit_json_str(),
                request.user.id,
            )
        )


class RevisionView(LandoView):
    @method_decorator(require_phabricator_api_key(optional=True, provide_client=True))
    def get(
        self,
        phab: PhabricatorClient,
        request: WSGIRequest,
        revision_id: int,
        *args,
        **kwargs,
    ) -> TemplateResponse:
        lando_user = request.user

        # This is added for backwards compatibility.
        stack = legacy_api.stacks.get(phab, revision_id)

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
        landing_jobs = legacy_api.transplants.get_list(phab, f"D{revision_id}")

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
            form.fields["landing_path"].initial = landing_path

            dryrun = legacy_api.transplants.dryrun(
                phab, lando_user, data={"landing_path": landing_path}
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

        # Hackbot check
        revisions_with_disallowed_authors = get_revisions_with_disallowed_authors(
            revisions
        )
        if revisions_with_disallowed_authors:
            # Take the first revision author, try to find an associated user in Lando.
            # If this is not possible, set the mailbox to the name of the user, which
            # must be modified before submitting.
            author_phid = revisions_with_disallowed_authors[0]["author"]["phid"]
            try:
                lando_user = Profile.objects.get(phabricator_phid=author_phid).user
            except Profile.DoesNotExist:
                form.fields["author_name"].initial = revisions_with_disallowed_authors[
                    0
                ]["author"]["real_name"]
            else:
                form.fields["author_name"].initial = lando_user.profile.userinfo["name"]
                form.fields["author_email"].initial = lando_user.profile.userinfo[
                    "email"
                ]
        else:
            form.fields["author_name"].initial = None
            form.fields["author_email"].initial = None

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
            "treestatus": (
                get_tree_by_name(landing_jobs.last().target_repo.short_name)
                if landing_jobs
                else None
            ),
            "revisions_with_disallowed_authors": revisions_with_disallowed_authors,
        }

        return TemplateResponse(
            request=request,
            template="stack/stack.html",
            context=context,
        )

    @force_auth_refresh
    @method_decorator(require_phabricator_api_key(optional=True, provide_client=True))
    def post(
        self,
        phab: PhabricatorClient,
        request: WSGIRequest,
        revision_id: int,
        *args,
        **kwargs,
    ) -> HttpResponseRedirect:
        form = TransplantRequestForm(request.POST)
        errors = []

        if not request.user.is_authenticated:
            errors.append("You must be logged in to request a landing")

        if form.is_valid() and not errors:
            form.cleaned_data["flags"] = (
                form.cleaned_data["flags"] if form.cleaned_data["flags"] else []
            )
            legacy_api.transplants.post(phab, request.user, data=form.cleaned_data)
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
