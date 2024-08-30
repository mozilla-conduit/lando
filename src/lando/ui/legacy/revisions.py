import logging


from lando.ui.legacy.forms import (
    TransplantRequestForm,
    UpliftRequestForm,
)
from lando.ui.legacy.stacks import draw_stack_graph, Edge, sort_stack_topological
from lando.ui.views import LandoView

from django.template.response import TemplateResponse
from django.http import JsonResponse, HttpResponseNotFound

logger = logging.getLogger(__name__)

# TODO: port this hook once lando-api is merged and hooks are implemented.
# revisions.before_request(set_last_local_referrer)


class Revision(LandoView):
    # TODO: auth is optional for this view.

    def get(self, request, revision_id, *args, **kwargs):
        # Request the entire stack.
        try:
            stack = api.request("GET", "stacks/D{}".format(revision_id))
        except LandoAPIError as e:
            if e.status_code == 404:
                raise RevisionNotFound(revision_id)
            else:
                raise

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
        transplants = api.request(
            "GET", "transplants", params={"stack_revision_id": "D{}".format(revision_id)}
        )

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
        if series and is_user_authenticated():
            landing_path = [
                {
                    "revision_id": revisions[phid]["id"],
                    "diff_id": revisions[phid]["diff"]["id"],
                }
                for phid in series
            ]
            landing_path_json = json.dumps(landing_path)
            form.landing_path.data = landing_path_json

            dryrun = api.request(
                "POST",
                "transplants/dryrun",
                require_auth0=True,
                json={"landing_path": landing_path},
            )
            form.confirmation_token.data = dryrun.get("confirmation_token")

            series = list(reversed(series))
            target_repo = repositories.get(revisions[series[0]]["repo_phid"])

        phids = set(revisions.keys())
        edges = set(Edge(child=e[0], parent=e[1]) for e in stack["edges"])
        order = sort_stack_topological(
            phids, edges, key=lambda x: int(revisions[x]["id"][1:])
        )
        drawing_width, drawing_rows = draw_stack_graph(phids, edges, order)

        annotate_sec_approval_workflow_info(revisions)

        # Are we showing the "sec-approval request submitted" dialog?
        # If we are then fill in its values.
        submitted_revision = request.args.get("show_approval_success")
        submitted_rev_url = None
        if submitted_revision:
            for rev in revisions.values():
                if rev["id"] == submitted_revision:
                    submitted_rev_url = rev["url"]
                    break

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

        return render_template(
            "stack/stack.html",
            revision_id="D{}".format(revision_id),
            series=series,
            landable=landable,
            dryrun=dryrun,
            stack=stack,
            rows=list(zip(reversed(order), reversed(drawing_rows))),
            drawing_width=drawing_width,
            transplants=transplants,
            revisions=revisions,
            revision_phid=revision,
            sec_approval_form=sec_approval_form,
            submitted_rev_url=submitted_rev_url,
            target_repo=target_repo,
            errors=errors,
            form=form,
            flags=target_repo["commit_flags"] if target_repo else [],
            existing_flags=existing_flags,
            uplift_request_form=uplift_request_form,
        )

    def post(*args, request, **kwargs):
        form = TransplantRequestForm()
        sec_approval_form = SecApprovalRequestForm()
        uplift_request_form = UpliftRequestForm()

        # Get the list of available uplift repos and populate the form with it.
        uplift_request_form.repository.choices = get_uplift_repos(api)
        uplift_request_form.revision_id.data = revision_id

        errors = []
        if form.is_submitted():
            if not is_user_authenticated():
                errors.append("You must be logged in to request a landing")

            elif not form.validate():
                for _, field_errors in form.errors.items():
                    errors.extend(field_errors)

            else:
                try:
                    api.request(
                        "POST",
                        "transplants",
                        require_auth0=True,
                        json={
                            "landing_path": json.loads(form.landing_path.data),
                            "confirmation_token": form.confirmation_token.data,
                            "flags": json.loads(form.flags.data),
                        },
                    )
                    # We don't actually need any of the data from the
                    # the submission. As long as an exception wasn't
                    # raised we're successful.
                    return redirect(url_for("revisions.revision", revision_id=revision_id))
                except LandoAPIError as e:
                    if not e.detail:
                        raise

                    errors.append(e.detail)
