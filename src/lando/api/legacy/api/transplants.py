# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import urllib.parse
from datetime import datetime
from typing import Optional

import kombu
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied

from lando.api.legacy.commit_message import format_commit_message
from lando.api.legacy.decorators import require_phabricator_api_key
from lando.api.legacy.phabricator import PhabricatorClient
from lando.api.legacy.projects import (
    CHECKIN_PROJ_SLUG,
    get_checkin_project_phid,
    get_release_managers,
    get_sec_approval_project_phid,
    get_secure_project_phid,
    get_testing_policy_phid,
    get_testing_tag_project_phids,
    project_search,
)
from lando.api.legacy.repos import (
    Repo,
    get_repos_for_env,
)
from lando.api.legacy.reviews import (
    approvals_for_commit_message,
    get_approved_by_ids,
    get_collated_reviewers,
    reviewers_for_commit_message,
)
from lando.api.legacy.revisions import (
    find_title_and_summary_for_landing,
    gather_involved_phids,
    get_bugzilla_bug,
    revision_is_secure,
    select_diff_author,
)
from lando.api.legacy.stacks import (
    RevisionData,
    build_stack_graph,
    calculate_landable_subgraphs,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)
from lando.api.legacy.transplants import (
    TransplantAssessment,
    check_landing_blockers,
    check_landing_warnings,
    convert_path_id_to_phid,
    get_blocker_checks,
)
from lando.api.legacy.users import user_search
from lando.api.legacy.validation import (
    parse_landing_path,
    revision_id_to_int,
)
from lando.main.models.landing_job import (
    LandingJob,
    LandingJobStatus,
    add_revisions_to_job,
)
from lando.main.models.revision import Revision
from lando.main.support import ProblemException, problem
from lando.utils.tasks import admin_remove_phab_project

logger = logging.getLogger(__name__)


def _parse_transplant_request(data: dict) -> dict:
    """Extract confirmation token, flags, and the landing path from provided data.

    Args
        data (dict): A dictionary representing the transplant request.

    Returns:
        dict: A dictionary containing the landing path, confirmation token and flags.
    """
    landing_path = parse_landing_path(data["landing_path"])

    if not landing_path:
        raise ProblemException(
            400,
            "Landing Path Required",
            "A non empty landing_path is required.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    flags = data.get("flags", [])

    # Confirmation token is optional. Convert usage of an empty
    # string to None as well to make using the API easier.
    confirmation_token = data.get("confirmation_token") or None

    return {
        "landing_path": landing_path,
        "confirmation_token": confirmation_token,
        "flags": flags,
    }


def _choose_middle_revision_from_path(path: list[tuple[int, int]]) -> int:
    if not path:
        raise ValueError("path must not be empty")

    # For even length we want to choose the greater index
    # of the two middle items, so doing floor division by 2
    # on the length, rather than max index, will give us the
    # desired index.
    return path[len(path) // 2][0]


def _find_stack_from_landing_path(
    phab: PhabricatorClient, landing_path: list[tuple[int, int]]
) -> tuple[set[str], set[tuple[str, str]]]:
    a_revision_id = _choose_middle_revision_from_path(landing_path)
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [a_revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        raise ProblemException(
            404,
            "Stack Not Found",
            "The stack does not exist or you lack permission to see it.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )
    return build_stack_graph(revision)


def _assess_transplant_request(
    lando_user: User,
    phab: PhabricatorClient,
    landing_path: list[tuple[int, int]],
    relman_group_phid: str,
) -> tuple[
    TransplantAssessment,
    Optional[list[tuple[dict, dict]]],
    Optional[Repo],
    Optional[RevisionData],
]:
    nodes, edges = _find_stack_from_landing_path(phab, landing_path)
    stack_data = request_extended_revision_data(phab, list(nodes))
    landing_path_phid = convert_path_id_to_phid(landing_path, stack_data)

    supported_repos = get_repos_for_env(settings.ENVIRONMENT)
    landable_repos = get_landable_repos_for_revision_data(stack_data, supported_repos)

    other_checks = get_blocker_checks(
        repositories=supported_repos,
        relman_group_phid=relman_group_phid,
        stack_data=stack_data,
    )

    landable, blocked = calculate_landable_subgraphs(
        stack_data, edges, landable_repos, other_checks=other_checks
    )

    assessment = check_landing_blockers(
        lando_user, landing_path_phid, stack_data, landable, landable_repos
    )
    if assessment.blocker is not None:
        return (assessment, None, None, None)

    # We have now verified that landable_path is valid and is indeed
    # landable (in the sense that it is a landable_subgraph, with no
    # revisions being blocked). Make this clear by using a different
    # value, and assume it going forward.
    valid_path = landing_path_phid

    # Now that we know this is a valid path we can convert it into a list
    # of (revision, diff) tuples.
    to_land = [stack_data.revisions[r_phid] for r_phid, _ in valid_path]
    to_land = [
        (r, stack_data.diffs[PhabricatorClient.expect(r, "fields", "diffPHID")])
        for r in to_land
    ]

    # To be a landable path the entire path must have the same
    # repository, so we can get away with checking only one.
    repo = stack_data.repositories[to_land[0][0]["fields"]["repositoryPHID"]]
    landing_repo = landable_repos[repo["phid"]]

    involved_phids = set()
    for revision, _ in to_land:
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)
    reviewers = {
        revision["phid"]: get_collated_reviewers(revision) for revision, _ in to_land
    }

    assessment = check_landing_warnings(
        phab,
        lando_user,
        to_land,
        repo,
        landing_repo,
        reviewers,
        users,
        projects,
        get_secure_project_phid(phab),
        get_testing_tag_project_phids(phab),
        get_testing_policy_phid(phab),
    )
    return (assessment, to_land, landing_repo, stack_data)


@require_phabricator_api_key(optional=True)
def dryrun(phab: PhabricatorClient, request, data: dict):
    lando_user = request.user
    if not lando_user.is_authenticated:
        raise PermissionDenied

    landing_path = _parse_transplant_request(data)["landing_path"]

    release_managers = get_release_managers(phab)
    if not release_managers:
        raise Exception("Could not find `#release-managers` project on Phabricator.")

    relman_group_phid = phab.expect(release_managers, "phid")
    assessment, *_ = _assess_transplant_request(
        lando_user, phab, landing_path, relman_group_phid
    )
    return assessment.to_dict()


@require_phabricator_api_key(optional=True)
def post(phab: PhabricatorClient, request, data: dict):
    lando_user = request.user
    if not lando_user.is_authenticated:
        raise PermissionDenied

    parsed_transplant_request = _parse_transplant_request(data)
    confirmation_token = parsed_transplant_request["confirmation_token"]
    flags = parsed_transplant_request["flags"]
    landing_path = parsed_transplant_request["landing_path"]

    logger.info(
        "transplant requested by user",
        extra={
            "has_confirmation_token": confirmation_token is not None,
            "landing_path": str(landing_path),
            "flags": flags,
        },
    )

    release_managers = get_release_managers(phab)
    if not release_managers:
        raise Exception("Could not find `#release-managers` project on Phabricator.")

    relman_group_phid = phab.expect(release_managers, "phid")

    assessment, to_land, landing_repo, stack_data = _assess_transplant_request(
        lando_user, phab, landing_path, relman_group_phid
    )

    assessment.raise_if_blocked_or_unacknowledged(confirmation_token)

    if not all((to_land, landing_repo, stack_data)):
        raise ValueError(
            "One or more values missing in access transplant request: "
            f"{to_land}, {landing_repo}, {stack_data}"
        )

    allowed_flags = [f[0] for f in landing_repo.commit_flags]
    invalid_flags = set(flags) - set(allowed_flags)
    if invalid_flags:
        raise ProblemException(
            400,
            "Invalid flags specified",
            f"Flags must be one or more of {allowed_flags}; "
            f"{invalid_flags} provided.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if assessment.warnings:
        # Log any warnings that were acknowledged, for auditing.
        logger.info(
            "Transplant with acknowledged warnings is being requested",
            extra={
                "landing_path": str(landing_path),
                "warnings": [
                    {"i": w.i, "revision_id": w.revision_id, "details": w.details}
                    for w in assessment.warnings
                ],
            },
        )

    involved_phids = set()

    revisions = [r[0] for r in to_land]

    for revision in revisions:
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    secure_project_phid = get_secure_project_phid(phab)

    # Take note of any revisions that the checkin project tag must be
    # removed from.
    checkin_phid = get_checkin_project_phid(phab)
    checkin_revision_phids = [
        r["phid"]
        for r in revisions
        if checkin_phid in phab.expect(r, "attachments", "projects", "projectPHIDs")
    ]

    sec_approval_project_phid = get_sec_approval_project_phid(phab)
    relman_phids = {
        member["phid"]
        for member in release_managers["attachments"]["members"]["members"]
    }

    lando_revisions = []
    revision_reviewers = {}

    # Build the patches to land.
    for revision, diff in to_land:
        reviewers = get_collated_reviewers(revision)
        accepted_reviewers = reviewers_for_commit_message(
            reviewers, users, projects, sec_approval_project_phid
        )

        # Find RelMan reviews for rewriting to `a=<reviewer>`.
        if landing_repo.approval_required:
            accepted_reviewers, approval_reviewers = approvals_for_commit_message(
                reviewers, users, projects, relman_phids, accepted_reviewers
            )
        else:
            approval_reviewers = []

        secure = revision_is_secure(revision, secure_project_phid)
        commit_description = find_title_and_summary_for_landing(phab, revision, secure)

        commit_message = format_commit_message(
            commit_description.title,
            get_bugzilla_bug(revision),
            accepted_reviewers,
            approval_reviewers,
            commit_description.summary,
            urllib.parse.urljoin(
                settings.PHABRICATOR_URL, "D{}".format(revision["id"])
            ),
            flags,
        )[1]
        author_name, author_email = select_diff_author(diff)
        timestamp = int(datetime.now().timestamp())

        # Construct the patch that will be transplanted.
        revision_id = revision["id"]
        diff_id = diff["id"]

        lando_revision = Revision.get_from_revision_id(revision_id)
        if not lando_revision:
            lando_revision = Revision(revision_id=revision_id)

        lando_revision.diff_id = diff_id
        lando_revision.save()

        revision_reviewers[lando_revision.id] = get_approved_by_ids(
            phab,
            PhabricatorClient.expect(revision, "attachments", "reviewers", "reviewers"),
        )

        patch_data = {
            "author_name": author_name,
            "author_email": author_email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        }

        raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
        lando_revision.set_patch(raw_diff, patch_data)
        lando_revision.save()
        lando_revisions.append(lando_revision)

    ldap_username = lando_user.email

    submitted_assessment = TransplantAssessment(
        blocker=(
            "This stack was submitted for landing by another user at the same time."
        )
    )
    stack_ids = [revision.revision_id for revision in lando_revisions]
    with LandingJob.lock_table:
        if (
            LandingJob.revisions_query(stack_ids)
            .filter(
                status__in=([LandingJobStatus.SUBMITTED, LandingJobStatus.IN_PROGRESS])
            )
            .count()
            != 0
        ):
            submitted_assessment.raise_if_blocked_or_unacknowledged(None)

        # Trigger a local transplant
        job = LandingJob(
            requester_email=ldap_username,
            repository_name=landing_repo.short_name,
            repository_url=landing_repo.url,
        )
        job.save()

    add_revisions_to_job(lando_revisions, job)
    logger.info(f"Setting {revision_reviewers} reviewer data on each revision.")
    for revision in lando_revisions:
        revision.data = {"approved_by": revision_reviewers[revision.id]}
        revision.save()

    # Submit landing job.
    job.status = LandingJobStatus.SUBMITTED
    job.set_landed_revision_diffs()
    job.save()

    logger.info(f"New landing job {job.id} created for {landing_repo.tree} repo.")

    # Asynchronously remove the checkin project from any of the landing
    # revisions that had it.
    for r_phid in checkin_revision_phids:
        try:
            admin_remove_phab_project.apply_async(
                args=(r_phid, checkin_phid),
                kwargs={"comment": f"#{CHECKIN_PROJ_SLUG} handled, landing queued."},
            )
        except kombu.exceptions.OperationalError:
            # Best effort is acceptable here, Transplant *is* going to land
            # these changes so it's better to return properly from the request.
            pass

    return {"id": job.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(phab: PhabricatorClient, request, stack_revision_id: str):
    """Return a list of Transplant objects"""
    revision_id_int = revision_id_to_int(stack_revision_id)

    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id_int]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        return problem(
            404,
            "Revision not found",
            "The revision does not exist or you lack permission to see it.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )
    nodes, edges = build_stack_graph(revision)
    revision_phids = list(nodes)
    revs = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": revision_phids},
        limit=len(revision_phids),
    )

    rev_ids = [phab.expect(r, "id") for r in phab.expect(revs, "data")]

    landing_jobs = LandingJob.revisions_query(rev_ids).all()

    return [job.serialize() for job in landing_jobs]
