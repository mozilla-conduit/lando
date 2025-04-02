import logging
import urllib.parse

from django.conf import settings
from django.http import Http404, HttpRequest

from lando.api.legacy.commit_message import format_commit_message
from lando.api.legacy.projects import (
    get_data_policy_review_phid,
    get_release_managers,
    get_sec_approval_project_phid,
    get_secure_project_phid,
    project_search,
)
from lando.api.legacy.reviews import (
    approvals_for_commit_message,
    get_collated_reviewers,
    reviewers_for_commit_message,
    serialize_reviewers,
)
from lando.api.legacy.revisions import (
    find_title_and_summary_for_display,
    gather_involved_phids,
    get_bugzilla_bug,
    revision_is_secure,
    serialize_author,
    serialize_diff,
    serialize_status,
)
from lando.api.legacy.stacks import (
    RevisionStack,
    build_stack_graph,
    get_diffs_for_revision,
    request_extended_revision_data,
)
from lando.api.legacy.transplants import (
    build_stack_assessment_state,
    run_landing_checks,
)
from lando.api.legacy.users import user_search
from lando.main.auth import require_phabricator_api_key
from lando.main.models import Repo
from lando.main.models.revision import Revision
from lando.utils.phabricator import PhabricatorClient

logger = logging.getLogger(__name__)

HTTP_404_STRING = "Revision does not exist or you do not have permission to view it"


@require_phabricator_api_key(optional=True)
def get(  # noqa: ANN201
    phab: PhabricatorClient, request: HttpRequest, revision_id: int
):
    """Get the stack a revision is part of.

    Args:
        revision_id: (int) ID of the revision in 'D{number}' format
    """
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        raise Http404(HTTP_404_STRING)

    nodes, edges = build_stack_graph(revision)
    try:
        stack_data = request_extended_revision_data(phab, list(nodes))
    except ValueError:
        raise Http404(HTTP_404_STRING)

    supported_repos = Repo.get_mapping()

    release_managers = get_release_managers(phab)
    if not release_managers:
        raise Exception("Could not find `#release-managers` project on Phabricator.")

    data_policy_review_phid = get_data_policy_review_phid(phab)
    if not data_policy_review_phid:
        raise Exception(
            "Could not find `#needs-data-classification` project on Phabricator."
        )

    relman_group_phid = str(phab.expect(release_managers, "phid"))

    stack = RevisionStack(set(stack_data.revisions.keys()), edges)
    stack_state = build_stack_assessment_state(
        phab,
        supported_repos,
        stack_data,
        stack,
        relman_group_phid,
        data_policy_review_phid,
    )
    # Run landing checks and update the stack state.
    run_landing_checks(stack_state)
    landable = stack_state.landable_stack.landable_paths()
    uplift_repos = [
        name for name, repo in supported_repos.items() if repo.approval_required
    ]

    involved_phids = set()
    for revision in stack_data.revisions.values():
        revision_diffs = get_diffs_for_revision(revision, stack_data.diffs)
        involved_phids.update(gather_involved_phids(revision, revision_diffs))

    involved_phids = list(involved_phids)

    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    secure_project_phid = get_secure_project_phid(phab)
    if not secure_project_phid:
        raise Exception("Could not find `#secure-revision` project on Phabricator.")

    sec_approval_project_phid = get_sec_approval_project_phid(phab)
    if not sec_approval_project_phid:
        raise Exception("Could not find `#sec-approval` project on Phabricator.")

    relman_phids = {
        member["phid"]
        for member in release_managers["attachments"]["members"]["members"]
    }

    revisions_response = []
    for _phid, phab_revision in stack_data.revisions.items():
        lando_revision = Revision.one_or_none(revision_id=phab_revision["id"])
        revision_phid = PhabricatorClient.expect(phab_revision, "phid")
        fields = PhabricatorClient.expect(phab_revision, "fields")
        diff_phid = PhabricatorClient.expect(fields, "diffPHID")
        repo_phid = PhabricatorClient.expect(fields, "repositoryPHID")
        diff = stack_data.diffs[diff_phid]
        human_revision_id = "D{}".format(PhabricatorClient.expect(phab_revision, "id"))
        revision_url = urllib.parse.urljoin(settings.PHABRICATOR_URL, human_revision_id)
        secure = revision_is_secure(phab_revision, secure_project_phid)
        commit_description = find_title_and_summary_for_display(
            phab, phab_revision, secure
        )
        bug_id = get_bugzilla_bug(phab_revision)
        reviewers = get_collated_reviewers(phab_revision)
        accepted_reviewers = reviewers_for_commit_message(
            reviewers, users, projects, sec_approval_project_phid
        )

        repo_short_name = PhabricatorClient.expect(
            stack_data.repositories[repo_phid], "fields", "shortName"
        )
        approval_required = (
            repo_short_name in supported_repos
            and supported_repos[repo_short_name].approval_required
        )

        # Only update the approvals/reviewers if `approval_required` is set on the repo.
        if approval_required:
            accepted_reviewers, approval_reviewers = approvals_for_commit_message(
                reviewers, users, projects, relman_phids, accepted_reviewers
            )
        else:
            approval_reviewers = []

        commit_message_title, commit_message = format_commit_message(
            commit_description.title,
            bug_id,
            accepted_reviewers,
            approval_reviewers,
            commit_description.summary,
            revision_url,
        )
        author_response = serialize_author(phab.expect(fields, "authorPHID"), users)

        blocked_reasons = stack_state.stack.nodes[revision_phid].get("blocked")

        revisions_response.append(
            {
                "id": human_revision_id,
                "phid": revision_phid,
                "status": serialize_status(phab_revision),
                "blocked_reasons": blocked_reasons,
                "bug_id": bug_id,
                "title": commit_description.title,
                "url": revision_url,
                "date_created": PhabricatorClient.to_datetime(
                    PhabricatorClient.expect(phab_revision, "fields", "dateCreated")
                ).isoformat(),
                "date_modified": PhabricatorClient.to_datetime(
                    PhabricatorClient.expect(phab_revision, "fields", "dateModified")
                ).isoformat(),
                "summary": commit_description.summary,
                "commit_message_title": commit_message_title,
                "commit_message": commit_message,
                "repo_phid": repo_phid,
                "diff": serialize_diff(diff),
                "author": author_response,
                "reviewers": serialize_reviewers(reviewers, users, projects, diff_phid),
                "is_secure": secure,
                "is_using_secure_commit_message": commit_description.sanitized,
                "lando_revision": (
                    lando_revision.serialize() if lando_revision else None
                ),
            }
        )

    repositories = []
    for phid in stack_data.repositories.keys():
        short_name = PhabricatorClient.expect(
            stack_data.repositories[phid], "fields", "shortName"
        )

        repo = supported_repos.get(short_name)
        landing_supported = repo is not None
        url = (
            repo.url
            if landing_supported
            else f"{settings.PHABRICATOR_URL}/source/{short_name}"
        )

        repositories.append(
            {
                "approval_required": landing_supported and repo.approval_required,
                "commit_flags": repo.commit_flags if repo else [],
                "landing_supported": landing_supported,
                "phid": phid,
                "short_name": short_name,
                "url": url,
            }
        )

    return {
        "repositories": repositories,
        "revisions": revisions_response,
        "edges": list(edges),
        "landable_paths": landable,
        "uplift_repositories": uplift_repos,
    }
