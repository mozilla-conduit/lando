import logging


from lando.ui.legacy.forms import (
    TransplantRequestForm,
    # UpliftRequestForm,
)
from lando.ui.legacy.stacks import draw_stack_graph, Edge, sort_stack_topological
from lando.ui.views import LandoView

from lando.api.legacy import api as legacy_api

from django.template.response import TemplateResponse
from django.shortcuts import redirect

import json

logger = logging.getLogger(__name__)

# TODO: port this hook once lando-api is merged and hooks are implemented.
# revisions.before_request(set_last_local_referrer)


class Revision(LandoView):
    def get(self, request, revision_id, *args, **kwargs):
        lando_user = request.user

        # This is added for backwards compatibility.
        stack = legacy_api.stacks.get(request, revision_id)

        form = TransplantRequestForm()
        errors = []

        # TODO: fix this later.
        # uplift_request_form = UpliftRequestForm()

        # # Get the list of available uplift repos and populate the form with it.
        # uplift_request_form.repository.choices = get_uplift_repos(api)
        # uplift_request_form.revision_id.data = revision_id

        # Build a mapping from phid to revision and identify
        # the data for the revision used to load this page.
        revision = None
        revisions = {}
        for r in stack["revisions"]:
            revisions[r["phid"]] = r
            if r["id"] == "D{}".format(revision_id):
                revision = r["phid"]

        # Build a mapping from phid to repository.
        repositories = {}
        for r in stack["repositories"]:
            repositories[r["phid"]] = r

        # Request all previous transplants for the stack.
        transplants = legacy_api.transplants.get_list(request, f"D{revision_id}")

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
                series = p[: p.index(revision) + 1]
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

            dryrun = legacy_api.transplants.dryrun(request, data={"landing_path": landing_path})
            series = list(reversed(series))
            target_repo = repositories.get(revisions[series[0]]["repo_phid"])

        phids = set(revisions.keys())
        edges = set(Edge(child=e[0], parent=e[1]) for e in stack["edges"])
        order = sort_stack_topological(
            phids, edges, key=lambda x: int(revisions[x]["id"][1:])
        )
        drawing_width, drawing_rows = draw_stack_graph(phids, edges, order)

        # Current implementation requires that all commits have the flags appended.
        # This may change in the future. What we do here is:
        # - if all commits have the flag, then disable the checkbox
        # - if any commits do not have the flag, then enable the checkbox

        if target_repo:
            existing_flags = {f[0]: False for f in target_repo["commit_flags"]}
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
            "rows": list(zip(reversed(order), reversed(drawing_rows))),
            "drawing_width": drawing_width,
            "transplants": transplants,
            "revisions": revisions,
            "revision_phid": revision,
            "target_repo": target_repo,
            "errors": errors,
            "form": form,
            "flags": target_repo["commit_flags"] if target_repo else [],
            "existing_flags": existing_flags,
            # "uplift_request_form": uplift_request_form,
        }

        return TemplateResponse(
            request=request,
            template="stack/stack.html",
            context=context,
        )

    def post(self, request, *args, **kwargs):
        form = TransplantRequestForm(request.POST)
        revision_id = int(kwargs["revision_id"])

        # uplift_request_form = UpliftRequestForm()

        # # Get the list of available uplift repos and populate the form with it.
        # uplift_request_form.repository.choices = get_uplift_repos(api)
        # uplift_request_form.revision_id.data = revision_id

        # if not is_user_authenticated():
        #     errors.append("You must be logged in to request a landing")

        if form.is_valid():
            form.cleaned_data["landing_path"] = json.loads(form.cleaned_data["landing_path"])
            form.cleaned_data["flags"] = json.loads(form.cleaned_data["flags"]) if form.cleaned_data["flags"] else []
            legacy_api.transplants.post(request, data=form.cleaned_data)
            # We don't actually need any of the data from the
            # the submission. As long as an exception wasn't
            # raised we're successful.
            return redirect("revisions-page", revision_id=revision_id)
        else:
            # TODO: parse errors and put into the list of errors.
            return
