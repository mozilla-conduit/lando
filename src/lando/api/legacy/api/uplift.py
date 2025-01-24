import logging

from django.http import Http404

from lando.api.legacy.api.stacks import HTTP_404_STRING
from lando.api.legacy.uplift import (
    create_uplift_revision,
    get_local_uplift_repo,
    get_uplift_conduit_state,
)
from lando.api.legacy.validation import revision_id_to_int
from lando.main.auth import require_authenticated_user, require_phabricator_api_key
from lando.utils.phabricator import PhabricatorClient

logger = logging.getLogger(__name__)


@require_authenticated_user
@require_phabricator_api_key(optional=False)
def create(phab: PhabricatorClient, request, data: dict) -> dict:
    """Create new uplift requests for requested repository & revision"""
    repository = data["repository"]
    repo_name = repository.name
    revision_id = revision_id_to_int(data["revision_id"])

    try:
        logger.info(
            "Checking approval state",
            extra={
                "revision": revision_id,
                "target_repository": repo_name,
            },
        )
        revision_data, revision_stack, target_repository = get_uplift_conduit_state(
            phab,
            revision_id=revision_id,
            target_repository_name=repo_name,
        )
        local_repo = get_local_uplift_repo(phab, target_repository)
        logger.info("Approval state is valid")
    except ValueError as err:
        logger.exception(
            "Hit an error retreiving uplift state from conduit.",
            extra={"error": str(err)},
        )
        raise Http404(HTTP_404_STRING)

    revision_phid = next(
        rev["phid"]
        for rev in revision_data.revisions.values()
        if rev["id"] == revision_id
    )

    # Get the most recent commit for `sourceControlBaseRevision`.
    base_revision = phab.expect(
        target_repository, "attachments", "metrics", "recentCommit", "identifier"
    )

    commit_stack = []
    for phid in revision_stack.iter_stack_from_root(dest=revision_phid):
        # Get the revision.
        revision = revision_data.revisions[phid]

        # Get the relevant diff.
        diff_phid = phab.expect(revision, "fields", "diffPHID")
        diff = revision_data.diffs[diff_phid]

        # Get the parent commit PHID from the stack if available.
        parent_phid = commit_stack[-1]["revision_phid"] if commit_stack else None

        try:
            # Create the revision.
            rev = create_uplift_revision(
                phab,
                local_repo,
                revision,
                diff,
                parent_phid,
                base_revision,
                target_repository,
            )
            commit_stack.append(rev)
        except Exception as e:
            logger.error(
                "Failed to create an uplift request",
                extra={
                    "revision": revision_id,
                    "repository": repository,
                    "error": str(e),
                },
            )

            if commit_stack:
                # Log information about any half-completed stack uplifts.
                logger.error(
                    "Uplift request completed partially, some resources are invalid.",
                    extra={
                        "commit_stack": commit_stack,
                        "repository": repository,
                    },
                )
            raise

    output = {rev["revision_phid"]: rev for rev in commit_stack}
    output["tip_differential"] = commit_stack[-1]

    return output
