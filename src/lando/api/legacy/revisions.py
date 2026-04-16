import logging
from collections import Counter
from datetime import datetime
from typing import (
    Any,
    NamedTuple,
    Optional,
)

from django.db import transaction

from lando.api.legacy.stacks import (
    get_diffs_by_phid,
    get_revisions_by_id,
)
from lando.main.models import Revision
from lando.utils.phabricator import (
    PhabricatorClient,
    PhabricatorRevisionStatus,
)

logger = logging.getLogger(__name__)


class CommitDescription(NamedTuple):
    """Represents the value of a commit's title line and commit summary (body)."""

    title: str
    summary: str
    sanitized: bool


def gather_involved_phids(revision: dict, revision_diffs: list[dict]) -> set[str]:
    """Return the set of Phobject phids involved in a revision.

    Receives a dict representing the revision, and a list of dicts representing every
    diff that is associated with that revision.

    Gathers the PHID of the author of the revision, the set of all reviewers on the
    revision, and any user who has pushed a diff to a revision.
    """
    attachments = PhabricatorClient.expect(revision, "attachments")

    entities = {PhabricatorClient.expect(revision, "fields", "authorPHID")}
    entities.update(
        {
            PhabricatorClient.expect(diff, "fields", "authorPHID")
            for diff in revision_diffs
        }
    )

    entities.update(
        {
            PhabricatorClient.expect(r, "reviewerPHID")
            for r in PhabricatorClient.expect(attachments, "reviewers", "reviewers")
        }
    )
    entities.update(
        {
            PhabricatorClient.expect(r, "reviewerPHID")
            for r in PhabricatorClient.expect(
                attachments, "reviewers-extra", "reviewers-extra"
            )
        }
    )
    return entities


def serialize_author(phid: str, user_search_data: dict) -> dict:
    out = {"phid": phid, "username": None, "real_name": None}
    author = user_search_data.get(phid)
    if author is not None:
        out["username"] = PhabricatorClient.expect(author, "fields", "username")
        out["real_name"] = PhabricatorClient.expect(author, "fields", "realName")

    return out


def serialize_diff(diff: dict) -> dict[str, Any]:
    author_name, author_email = select_diff_author(diff)
    fields = PhabricatorClient.expect(diff, "fields")

    return {
        "id": PhabricatorClient.expect(diff, "id"),
        "phid": PhabricatorClient.expect(diff, "phid"),
        "date_created": PhabricatorClient.to_datetime(
            PhabricatorClient.expect(fields, "dateCreated")
        ).isoformat(),
        "date_modified": PhabricatorClient.to_datetime(
            PhabricatorClient.expect(fields, "dateModified")
        ).isoformat(),
        "author": {"name": author_name or "", "email": author_email or ""},
    }


def serialize_status(revision: dict) -> dict:
    status_value = PhabricatorClient.expect(revision, "fields", "status", "value")
    status = PhabricatorRevisionStatus.from_status(status_value)

    if status is PhabricatorRevisionStatus.UNEXPECTED_STATUS:
        logger.warning(
            "Revision had unexpected status",
            extra={
                "id": PhabricatorClient.expect(revision, "id"),
                "value": status_value,
            },
        )
        return {"closed": False, "value": None, "display": "Unknown"}

    return {
        "closed": status.closed,
        "value": status.value,
        "display": status.output_name,
    }


def select_diff_author(diff: dict) -> tuple[Optional[str], Optional[str]]:
    commits = PhabricatorClient.expect(diff, "attachments", "commits", "commits")
    if not commits:
        return None, None

    authors = [c.get("author", {}) for c in commits]
    authors = Counter((a.get("name"), a.get("email")) for a in authors)
    authors = authors.most_common(1)
    return authors[0][0] if authors else (None, None)


def get_bugzilla_bug(revision: dict) -> Optional[int]:
    bug = PhabricatorClient.expect(revision, "fields").get("bugzilla.bug-id")
    return int(bug) if bug else None


def blocker_diff_author_is_known(*, diff: dict, **kwargs) -> Optional[str]:
    author_name, author_email = select_diff_author(diff)
    if author_name and author_email:
        return None

    return (
        "Diff does not have proper author information in Phabricator. "
        "See the Lando FAQ for help with this error."
    )


def revision_has_needs_data_classification_tag(
    revision: dict, data_policy_review_phid: str
) -> bool:
    """Return `True` if the `needs-data-classification` tag is not present on a revision."""
    return (
        data_policy_review_phid in revision["attachments"]["projects"]["projectPHIDs"]
    )


def revision_is_secure(revision: dict, secure_project_phid: str) -> bool:
    """Does the given revision contain security-sensitive data?

    Such revisions should be handled according to the Security Bug Approval Process.
    See https://wiki.mozilla.org/Security/Bug_Approval_Process.

    Args:
        revision: A dict of the revision data from differential.revision.search
            with the 'projects' attachment.
        secure_project_phid: The PHID of the Phabricator project used to tag
            secure revisions.
    """
    revision_project_tags = PhabricatorClient.expect(
        revision, "attachments", "projects", "projectPHIDs"
    )
    return secure_project_phid in revision_project_tags


def revision_needs_testing_tag(
    revision: dict,
    repo: dict,
    testing_tag_project_phids: list[str],
    testing_policy_phid: str,
) -> bool:
    """Does the given revision contain the appropriate testing tag?

    To enable this check for a particular repo, the repo needs to be associated with
    the "needs-testing-tag" project.

    Args:
        revision (dict): A Phabricator revision.
        testing_tag_project_phids (list): A list of all testing policy tag PHIDs.
        testing_policy_phid (str): The PHID of the `testing-policy` tag, normally
            associated with a repo.

    Returns:
        bool: True if the revision needs a testing policy tag, else False.
    """
    # Check if the repo has a testing-policy tag.
    if testing_policy_phid in repo["attachments"]["projects"]["projectPHIDs"]:
        # Check if the revision contains one of the testing policy tags.
        revision_project_tags = revision["attachments"]["projects"]["projectPHIDs"]
        return not set(testing_tag_project_phids) & set(revision_project_tags)
    return False


def find_title_and_summary_for_display(
    phab: PhabricatorClient, revision: dict, secure: bool
) -> CommitDescription:
    """Find a commit's title and summary for display in Lando UI.

    This function is intended to get the commit title and summary for display to the
    end user in Lando UI. This function does NOT produce a commit title and summary
    that are suitable for landing code in a source tree because this function may
    return placeholder text for the UI.

    Args:
        phab: A PhabricatorClient instance.
        revision: A Phabricator Revision object used to generate the commit title
            and summary.
        secure: Bool indicating the revision is security-sensitive and subject to the
            sec-approval process.

    Returns: A CommitDescription object that holds the title and summary. The values
        depend on the public or secure status of the revision.
    """
    return CommitDescription(
        title=PhabricatorClient.expect(revision, "fields", "title"),
        summary=PhabricatorClient.expect(revision, "fields", "summary"),
        sanitized=False,
    )


def find_title_and_summary_for_landing(
    phab: PhabricatorClient, revision: dict, secure: bool
) -> CommitDescription:
    """Find a commit's title and summary for placing in a commit message.

    This function returns the title and summary so that it can be placed directly
    in a commit message and landed in-tree.  If this function fails to find a
    suitable commit message then an error will be raised.

    Args:
        phab: A PhabricatorClient instance.
        revision: A Phabricator Revision object used to generate the commit title
            and summary.
        secure: Bool indicating the revision is security-sensitive and subject to the
            sec-approval process.

    Returns: A CommitDescription object that holds the title and summary. The values
        depend on the public or secure status of the revision.
    """
    return CommitDescription(
        title=PhabricatorClient.expect(revision, "fields", "title"),
        summary=PhabricatorClient.expect(revision, "fields", "summary"),
        sanitized=False,
    )


def fetch_raw_diff_and_save(
    phab: PhabricatorClient,
    revision_id: int,
    diff: dict,
    commit_message: str,
) -> Revision:
    """Fetch the raw diff from Phabricator and save a `Revision` record.

    This is the shared core for building `Revision` objects from Phabricator
    data, used by both the regular landing flow and the uplift request flow.

    Args:
        phab: A PhabricatorClient instance.
        revision_id: The integer revision ID (e.g. 123 for D123).
        diff: A Phabricator diff dict with the `commits` attachment.
        commit_message: The full commit message to embed in the patch.
    """
    diff_id = PhabricatorClient.expect(diff, "id")
    author_name, author_email = select_diff_author(diff)

    logger.debug("Fetching raw diff for D%s (diff %s).", revision_id, diff_id)
    raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff_id)

    patch_data = {
        "author_name": author_name or "",
        "author_email": author_email or "",
        "commit_message": commit_message,
        "timestamp": str(int(datetime.now().timestamp())),
    }

    with transaction.atomic():
        revision, created = Revision.objects.update_or_create(
            revision_id=revision_id,
            defaults={"diff_id": diff_id},
        )
        revision.set_patch(raw_diff, patch_data)
        revision.save()

    logger.debug("Saved Revision D%s with diff %s.", revision_id, diff_id)
    return revision


def ensure_revisions_from_phabricator(
    phab: PhabricatorClient, revision_ids: list[int]
) -> list[Revision]:
    """Return `Revision` records for each ID, fetching missing ones from Phabricator.

    Existing records are returned as-is. Missing records are fetched from
    Phabricator in batch (single API call for revisions and diffs) and saved
    locally before being returned.

    This is used when `Revision` records are needed but patches have not
    landed on autoland yet (e.g. for pre-autoland uplift requests).
    """
    existing = list(Revision.objects.filter(revision_id__in=revision_ids))
    existing_ids = {revision.revision_id for revision in existing}
    missing_ids = [rid for rid in revision_ids if rid not in existing_ids]

    if existing_ids:
        logger.debug("Revisions already exist locally: %s.", existing_ids)

    if not missing_ids:
        return existing

    logger.debug(
        "Revisions not found locally, fetching from Phabricator: %s.", missing_ids
    )

    try:
        revisions_by_phid = get_revisions_by_id(phab, missing_ids)
    except ValueError as exc:
        raise ValueError(
            f"One or more revisions not found on Phabricator: "
            f"{', '.join(f'D{rid}' for rid in missing_ids)}."
        ) from exc

    diff_phids = [
        phab.expect(rev, "fields", "diffPHID") for rev in revisions_by_phid.values()
    ]
    diffs_by_phid = get_diffs_by_phid(phab, diff_phids)

    fetched = []
    for revision_data in revisions_by_phid.values():
        rev_id = phab.expect(revision_data, "id")
        diff_phid = phab.expect(revision_data, "fields", "diffPHID")

        if diff_phid not in diffs_by_phid:
            raise ValueError(f"No diff found for revision D{rev_id} on Phabricator.")

        diff = diffs_by_phid[diff_phid]

        # Build a primitive commit message.
        title = phab.expect(revision_data, "fields", "title")
        summary = revision_data["fields"].get("summary", "")
        commit_message = f"{title}\n\n{summary}".strip()

        revision = fetch_raw_diff_and_save(phab, rev_id, diff, commit_message)
        fetched.append(revision)

    return existing + fetched


def seed_revisions_from_phabricator(
    phab: PhabricatorClient, raw_revision_ids: list[str]
) -> None:
    """Ensure `Revision` records exist for each ID, fetching from Phabricator if needed.

    Raises `ValueError` on the first revision ID that is not a valid integer or
    that cannot be seeded from Phabricator.
    """
    revision_ids = []
    for raw_id in raw_revision_ids:
        try:
            revision_ids.append(int(raw_id))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid revision ID: {raw_id}")

    if revision_ids:
        ensure_revisions_from_phabricator(phab, revision_ids)
