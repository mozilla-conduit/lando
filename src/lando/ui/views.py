from django.contrib import messages
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.views import View

from lando.api.legacy import api as legacy_api
from lando.api.support import dryrun, get_stack_landing_jobs, submit_landing_job
from lando.main.auth import force_auth_refresh, require_phabricator_api_key
from lando.main.models import JobStatus, LandingJob, Profile, Repo
from lando.main.support import get_revisions_with_disallowed_authors
from lando.ui.legacy.forms import TransplantRequestForm
from lando.ui.legacy.stacks import Edge, draw_stack_graph, sort_stack_topological
from lando.ui.uplift.context import UpliftContext
from lando.utils import treestatus
from lando.utils.phabricator import PhabricatorClient


class LandoView(View):
    pass


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
        landing_jobs = get_stack_landing_jobs(phab, f"D{revision_id}")

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

        dryrun_result = None
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

            dryrun_result = dryrun(
                phab, lando_user, data={"landing_path": landing_path}
            )
            form.fields["confirmation_token"].initial = dryrun_result[
                "confirmation_token"
            ]
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
            "dryrun": dryrun_result,
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
                treestatus.get_treestatus_data(
                    landing_jobs.last().target_repo.short_name
                )
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
            submit_landing_job(phab, request.user, data=form.cleaned_data)
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


class IndexView(LandoView):
    MAX_JOBS_HISTORY = 10

    def get(self, request: WSGIRequest) -> TemplateResponse:
        context = {"MAX_JOBS_HISTORY": self.MAX_JOBS_HISTORY}
        if request.user.is_authenticated:
            context["pending_jobs"] = LandingJob.objects.filter(
                requester_email=request.user.email, status__in=JobStatus.pending()
            )
            context["final_jobs"] = LandingJob.objects.filter(
                requester_email=request.user.email,
                status__in=JobStatus.final(),
            ).order_by("-updated_at")[: self.MAX_JOBS_HISTORY]

        return TemplateResponse(request=request, template="home.html", context=context)
