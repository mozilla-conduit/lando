from typing import Callable
from unittest import mock

import pytest

from lando.api.legacy.api import stacks
from lando.api.legacy.revisions import (
    MergeConflictStatus,
    MergeConflictVerdict,
    blocker_diff_author_is_known,
    ensure_revision_from_github,
    ensure_revisions_from_phabricator,
    fetch_raw_diff_and_save,
    get_base_revision_from_diff,
    get_first_public_parent_from_diff,
    revision_is_secure,
    revision_needs_testing_tag,
)
from lando.api.legacy.transplants import warning_diff_author_is_hackbot
from lando.main.models.revision import Revision
from lando.utils.github import PullRequest

pytestmark = pytest.mark.usefixtures("docker_env_vars")


def test_check_diff_author_is_known_with_author(phabdouble):
    # Adds author information by default.
    d = phabdouble.diff()
    phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert blocker_diff_author_is_known(diff=diff) is None


def test_check_diff_author_is_known_with_unknown_author(phabdouble):
    # No commits for no author data.
    d = phabdouble.diff(commits=[])
    phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert blocker_diff_author_is_known(diff=diff) is not None


@pytest.mark.parametrize(
    "username,email,has_warning",
    [
        ("Hackbot", "hackbot@mozilla.tld", True),
        ("HaCkbOt", "hAckbOt@mOzilla.TLD", True),
        ("Something else", "hackbot@mozilla.tld", True),
        ("Something else", "something_else@mozilla.tld", False),
    ],
)
def test_check_diff_author_is_hackbot(username, email, has_warning, phabdouble):
    author = phabdouble.user(username=username, email=email)
    d = phabdouble.diff(author=author)
    r = phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})
    revision = phabdouble.api_object_for(r)

    if has_warning:
        assert (
            warning_diff_author_is_hackbot(
                revision=revision, diff=diff, stack_state=None
            ).display
            == "Commit contains author that will be modified before landing."
        )
    else:
        assert (
            warning_diff_author_is_hackbot(
                revision=revision, diff=diff, stack_state=None
            )
            is None
        )


def test_secure_api_flag_on_public_revision_is_false(
    db,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
    secure_project,
):
    repo = phabdouble.repo(name="test-repo")
    public_project = phabdouble.project("public")
    revision = phabdouble.revision(projects=[public_project], repo=repo)

    result = stacks.get(phabdouble.get_phabricator_client(), revision["id"])
    response_revision = result["revisions"].pop()
    assert not response_revision["is_secure"]


def test_secure_api_flag_on_secure_revision_is_true(
    db,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
    secure_project,
):
    repo = phabdouble.repo(name="test-repo")
    revision = phabdouble.revision(projects=[secure_project], repo=repo)

    result = stacks.get(phabdouble.get_phabricator_client(), revision["id"])
    response_revision = result["revisions"].pop()
    assert response_revision["is_secure"]


def test_public_revision_is_not_secure(phabdouble, secure_project):
    public_project = phabdouble.project("public")
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[public_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert not revision_is_secure(revision, secure_project["phid"])


def test_secure_revision_is_secure(phabdouble, secure_project):
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert revision_is_secure(revision, secure_project["phid"])


def test_revision_does_not_need_testing_tag(phabdouble):
    testing_tag_projects = [{"phid": "testing-tag-phid"}]
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=testing_tag_projects, repo=repo)
    assert not revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_revision_needs_testing_tag(phabdouble):
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=[], repo=repo)
    assert revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_repo_does_not_have_testing_policy(phabdouble):
    repo = phabdouble.repo(projects=[])
    revision = phabdouble.revision(projects=[], repo=repo)
    assert not revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def commits_attachment(first_public_parent: str | None) -> list[dict]:
    """Return a `commits` attachment entry recording `first_public_parent`.

    Passing `None` omits the key entirely, as diffs submitted before bug 2068637
    do.
    """
    commit = {
        "identifier": "abc123",
        "tree": None,
        "parents": [],
        "author": {
            "name": "Test User",
            "email": "test@example.com",
            "raw": "Test User <test@example.com>",
            "epoch": 0,
        },
        "message": "Bug 1 - Test commit",
    }

    if first_public_parent is not None:
        commit["firstPublicParent"] = first_public_parent

    return [commit]


@pytest.mark.parametrize(
    "first_public_parent,expected",
    [
        pytest.param("a" * 40, "a" * 40, id="happy-path"),
        pytest.param(None, "", id="no-hash"),
        pytest.param("not-a-hash", "", id="invalid-hash"),
        pytest.param("A" * 40, "", id="uppercase-hash"),
        pytest.param("a" * 39, "", id="hash-too-short"),
        pytest.param("a" * 41, "", id="hash-too-long"),
        pytest.param("a" * 40 + "\n", "", id="hash-with-newline"),
    ],
)
def test_get_first_public_parent_from_diff_returns_first_ancestor_identifier(
    phabdouble, first_public_parent, expected
):
    """The `firstPublicParent` ref identifier is returned when present."""
    diff = phabdouble.api_object_for(
        phabdouble.diff(commits=commits_attachment(first_public_parent)),
        attachments={"commits": True},
    )
    assert get_first_public_parent_from_diff(diff) == expected, (
        "`get_first_public_parent_from_diff` should return the firstPublicParent "
        "ref identifier if it exists. Else, it should return an empty string."
    )


def test_get_base_revision_from_diff_returns_base_identifier():
    """The `base` ref identifier is returned when present."""
    diff = {"fields": {"refs": [{"type": "base", "identifier": "abc123"}]}}
    assert get_base_revision_from_diff(diff) == "abc123", (
        "`get_base_revision_from_diff` should return the base ref identifier."
    )


def test_get_base_revision_from_diff_ignores_other_refs():
    """Non-`base` refs are ignored, returning the empty string."""
    diff = {"fields": {"refs": [{"type": "branch", "name": "HEAD"}]}}
    assert get_base_revision_from_diff(diff) == "", (
        "`get_base_revision_from_diff` should ignore non-base refs."
    )


def test_get_base_revision_from_diff_handles_missing_refs():
    """An empty string is returned when no refs are present."""
    assert get_base_revision_from_diff({"fields": {}}) == "", (
        "`get_base_revision_from_diff` should return an empty string without refs."
    )


# Maps each key Phabricator sends to the `MergeConflictStatus` field it lands on,
# along with the conversion `from_revision` applies on the way.
MERGE_CONFLICT_PAYLOAD_FIELDS = {
    "status": ("status", MergeConflictVerdict),
    "reason": ("reason", str),
    "checkedAgainstBaseCommit": ("base_commit", str),
    "checkedAgainstCommit": ("target_commit", str),
    "checkedAgainstDiffID": ("diff_id", int),
    "epoch": ("epoch", int),
    "isStale": ("is_stale", bool),
}

# Keys Phabricator sends that Lando has no use for. `isStale` already answers the
# only question the diff PHID would, and the base revision is named in `reason`.
MERGE_CONFLICT_IGNORED_PAYLOAD_KEYS = {
    "checkedAgainstDiffPHID",
    "checkedAgainstBaseRevisionPHID",
}


def test_merge_conflict_status_from_revision_parses_payload(
    merge_conflict_revision: Callable,
):
    """Every key Phabricator sends is either parsed or deliberately ignored."""
    revision = merge_conflict_revision()
    payload = revision["fields"]["merge.conflict.status"]

    status = MergeConflictStatus.from_revision(revision)

    assert payload.keys() == (
        MERGE_CONFLICT_PAYLOAD_FIELDS.keys() | MERGE_CONFLICT_IGNORED_PAYLOAD_KEYS
    ), "Every key Phabricator sends should be accounted for, parsed or ignored."

    for key, (field, convert) in MERGE_CONFLICT_PAYLOAD_FIELDS.items():
        assert getattr(status, field) == convert(payload[key]), (
            f"`{key}` should be parsed onto `MergeConflictStatus.{field}`."
        )


def test_merge_conflict_status_from_revision_without_field():
    """A revision without the custom field has no verdict."""
    assert MergeConflictStatus.from_revision({"fields": {}}) is None, (
        "`MergeConflictStatus.from_revision` should return `None` without the field."
    )


def test_merge_conflict_status_from_revision_without_status():
    """A payload that records no status is as unusable as a missing one."""
    revision = {"fields": {"merge.conflict.status": {"epoch": 1757001600}}}

    assert MergeConflictStatus.from_revision(revision) is None, (
        "`MergeConflictStatus.from_revision` should return `None` without a status."
    )


@pytest.mark.parametrize(
    "status,verdict",
    (
        ("conflict", MergeConflictVerdict.CONFLICT),
        ("clean", MergeConflictVerdict.CLEAN),
        ("unknown", MergeConflictVerdict.UNKNOWN),
        ("a-verdict-lando-does-not-know", MergeConflictVerdict.UNKNOWN),
    ),
)
def test_merge_conflict_status_has_merge_conflict(
    merge_conflict_revision: Callable, status: str, verdict: MergeConflictVerdict
):
    """Only an explicit `conflict` verdict counts as a conflict."""
    parsed = MergeConflictStatus.from_revision(merge_conflict_revision(status=status))

    assert parsed.status is verdict, (
        f"A `{status}` payload should parse as `{verdict}`."
    )
    assert parsed.has_merge_conflict is (verdict is MergeConflictVerdict.CONFLICT), (
        f"`has_merge_conflict` should only be `True` for `conflict`, not `{status}`."
    )


def test_merge_conflict_status_from_revision_parses_an_unknown_verdict(
    merge_conflict_revision: Callable,
):
    """An `unknown` verdict records no commits, since no merge was performed."""
    status = MergeConflictStatus.from_revision(
        merge_conflict_revision(
            status="unknown",
            reason="Mergeability could not be determined.",
            checkedAgainstCommit=None,
            checkedAgainstBaseCommit=None,
        )
    )

    assert status.status is MergeConflictVerdict.UNKNOWN, (
        "An `unknown` payload should parse as an undecided verdict."
    )
    assert not status.has_merge_conflict, "An `unknown` verdict should not conflict."
    assert status.base_commit is None and status.target_commit is None, (
        "An `unknown` verdict should carry no commits."
    )
    assert status.describe_check() == (
        "Last checked diff 456, at 2025-09-04 16:00 UTC."
    ), "`describe_check` should name only the inputs the verdict recorded."


def test_merge_conflict_status_stale_verdict_is_still_a_conflict(
    merge_conflict_revision: Callable,
):
    """A stale verdict is the most recent one Phabricator has, so it still counts."""
    status = MergeConflictStatus.from_revision(merge_conflict_revision(isStale=True))

    assert status.is_stale, "An `isStale` payload should parse as a stale verdict."
    assert status.has_merge_conflict, (
        "A stale `conflict` verdict should still report a merge conflict."
    )


def test_merge_conflict_status_describe_check(
    merge_conflict_revision: Callable,
):
    """The description names the diff, base commit and time of the check."""
    status = MergeConflictStatus.from_revision(merge_conflict_revision())

    assert status.describe_check() == (
        f"Last checked diff 456, base commit {'a' * 40}, at 2025-09-04 16:00 UTC."
    ), "`describe_check` should name every recorded input."


def test_merge_conflict_status_describe_check_without_inputs(
    merge_conflict_revision: Callable,
):
    """A verdict recording no inputs has no reference to describe."""
    status = MergeConflictStatus.from_revision(
        merge_conflict_revision(
            checkedAgainstDiffID=None, checkedAgainstBaseCommit=None, epoch=None
        )
    )

    assert status.describe_check() is None, (
        "`describe_check` should return `None` without any recorded inputs."
    )


@pytest.mark.django_db
def test_fetch_raw_diff_and_save_creates_new_revision(phabdouble):
    """Creating a new `Revision` via `fetch_raw_diff_and_save`."""
    phab_revision = phabdouble.revision(title="Bug 1 - Test commit")
    phab = phabdouble.get_phabricator_client()
    diff = phabdouble.api_object_for(
        phabdouble.diff(revision=phab_revision, commits=commits_attachment("a" * 40)),
        attachments={"commits": True},
    )

    revision = fetch_raw_diff_and_save(
        phab, phab_revision["id"], diff, "Bug 1 - Test commit"
    )

    assert revision.revision_id == phab_revision["id"], (
        "`revision_id` should match the provided value."
    )
    assert revision.diff_id == diff["id"], "`diff_id` should match the diff."
    assert revision.commit_message == "Bug 1 - Test commit", (
        "`commit_message` should be set from the provided message."
    )
    assert revision.base_revision == get_base_revision_from_diff(diff), (
        "`base_revision` should be set from the diff's base ref."
    )
    assert revision.base_revision, (
        "`base_revision` should be populated from the default diff base ref."
    )

    assert revision.first_public_parent, (
        "`first_public_parent` should be populated from the firstPublicParent key "
        "of the local:commits diff property."
    )
    assert revision.first_public_parent == get_first_public_parent_from_diff(diff), (
        "`first_public_parent` should be set from the firstPublicParent key "
        "of the local:commits diff property."
    )


@pytest.mark.django_db
def test_fetch_raw_diff_and_save_updates_existing_revision(phabdouble):
    """Updating an existing `Revision` with new data."""
    phab_revision = phabdouble.revision(title="Updated message")
    phab = phabdouble.get_phabricator_client()
    diff = phabdouble.api_object_for(
        phabdouble.diff(revision=phab_revision), attachments={"commits": True}
    )
    existing = Revision.objects.create(revision_id=phab_revision["id"], diff_id=1)

    revision = fetch_raw_diff_and_save(
        phab, phab_revision["id"], diff, "Updated message"
    )

    assert revision.pk == existing.pk, (
        "Should update the existing Revision, not create a new one."
    )
    assert revision.diff_id == diff["id"], "`diff_id` should be updated."
    assert revision.commit_message == "Updated message", (
        "`commit_message` should reflect the new data."
    )


@pytest.mark.django_db
def test_ensure_revisions_from_phabricator_returns_existing(phabdouble):
    """Returns existing `Revision` records without Phabricator API calls."""
    existing = Revision.objects.create(revision_id=999, diff_id=1)
    phab = phabdouble.get_phabricator_client()

    revisions = ensure_revisions_from_phabricator(phab, [999])

    assert len(revisions) == 1, "Should return exactly one Revision."
    assert revisions[0].pk == existing.pk, "Should return the existing Revision."


@pytest.mark.django_db
def test_ensure_revisions_from_phabricator_creates_from_phabricator(phabdouble):
    """Creates `Revision` records by fetching data from Phabricator."""
    phab_revision = phabdouble.revision(
        title="Bug 1 - Test patch", summary="Patch summary."
    )
    phab = phabdouble.get_phabricator_client()

    revisions = ensure_revisions_from_phabricator(phab, [phab_revision["id"]])

    assert len(revisions) == 1, "Should return exactly one Revision."
    revision = revisions[0]
    assert revision.revision_id == phab_revision["id"], "`revision_id` should match."
    assert revision.diff_id is not None, "`diff_id` should be populated."
    assert "Bug 1 - Test patch" in revision.commit_message, (
        "`commit_message` should contain the revision title."
    )
    assert "Patch summary." in revision.commit_message, (
        "`commit_message` should contain the revision summary."
    )


@pytest.mark.django_db
def test_ensure_revisions_from_phabricator_raises_on_missing_revision(phabdouble):
    """Raises `ValueError` when a revision does not exist on Phabricator."""
    phab = phabdouble.get_phabricator_client()

    with pytest.raises(ValueError, match="not found on Phabricator"):
        ensure_revisions_from_phabricator(phab, [999999])


def set_mock_pull_request_diff(
    mock_pr: mock.MagicMock, diff: str | Exception
) -> mock.PropertyMock:
    """Give `mock_pr` a `diff` property, returning it so tests can count fetches.

    An exception for `diff` makes reading the property raise it, like a stale PR.
    """
    if isinstance(diff, Exception):
        diff_property = mock.PropertyMock(side_effect=diff)
    else:
        diff_property = mock.PropertyMock(return_value=diff)
    type(mock_pr).diff = diff_property
    return diff_property


@pytest.mark.django_db
def test_ensure_revision_from_github_reuses_matching_snapshot(
    mock_github_pull_request, github_pr_diff
):
    """A `Revision` seeded from the same head SHA is reused as-is."""
    mock_pr = mock_github_pull_request(number=1, title="title")
    diff_property = set_mock_pull_request_diff(mock_pr, github_pr_diff)

    snapshot = Revision.objects.create(
        pull_number=mock_pr.number,
        pull_head_sha=mock_pr.head_sha,
        pull_base_sha=mock_pr.base_sha,
        patch_data={
            "author_name": "User",
            "author_email": "user@example.com",
            "commit_message": mock_pr.commit_message,
            "timestamp": "1761017419",
        },
    )
    snapshot.set_patch(github_pr_diff)
    snapshot.save()

    revision = ensure_revision_from_github(mock_pr)

    assert revision.pk == snapshot.pk, (
        "The existing snapshot for this head SHA should be reused."
    )
    assert Revision.objects.count() == 1, "No new `Revision` should be created."
    assert diff_property.call_count == 0, "GitHub should not be queried for a diff."


@pytest.mark.django_db
def test_ensure_revision_from_github_ignores_stale_snapshot(
    mock_github_pull_request, github_pr_diff
):
    """A `Revision` for an older head SHA of the same PR is not reused."""
    mock_pr = mock_github_pull_request(number=1, title="title")
    diff_property = set_mock_pull_request_diff(mock_pr, github_pr_diff)

    stale = Revision.objects.create(
        pull_number=mock_pr.number,
        pull_head_sha="ccc123",
        pull_base_sha=mock_pr.base_sha,
        patch="stale patch",
    )

    revision = ensure_revision_from_github(mock_pr)

    assert revision.pk != stale.pk, (
        "A snapshot of an outdated head SHA should not be reused."
    )
    assert revision.pull_head_sha == mock_pr.head_sha, (
        "The new `Revision` should track the current head SHA."
    )
    assert diff_property.call_count == 1, (
        "The current head's diff should be fetched from GitHub."
    )


@pytest.mark.django_db
def test_ensure_revision_from_github_creates_from_github(
    mock_github_pull_request, github_pr_diff
):
    """With no local `Revision`, one is seeded from the GitHub diff."""
    mock_pr = mock_github_pull_request(number=1, title="title")
    diff_property = set_mock_pull_request_diff(mock_pr, github_pr_diff)

    revision = ensure_revision_from_github(mock_pr)

    author_name, author_email = mock_pr.author

    assert Revision.objects.count() == 1, "Exactly one `Revision` should be created."
    assert revision.pull_number == mock_pr.number, (
        "`pull_number` should match the pull request."
    )
    assert revision.pull_head_sha == mock_pr.head_sha, (
        "`pull_head_sha` should match the pull request."
    )
    assert revision.pull_base_sha == mock_pr.base_sha, (
        "`pull_base_sha` should match the pull request."
    )
    assert revision.patch_data["author_name"] == author_name, (
        "`author_name` should come from the pull request author."
    )
    assert revision.patch_data["author_email"] == author_email, (
        "`author_email` should come from the pull request author."
    )
    assert revision.patch_data["commit_message"] == mock_pr.commit_message, (
        "`commit_message` should come from the pull request."
    )
    assert github_pr_diff in revision.patch, (
        "The patch should contain the diff fetched from GitHub."
    )
    assert diff_property.call_count == 1, "The diff should be fetched once."


@pytest.mark.django_db
def test_ensure_revision_from_github_seeds_once_per_head_sha(
    mock_github_pull_request, github_pr_diff
):
    """Seeding the same pull request state twice reuses the first `Revision`."""
    mock_pr = mock_github_pull_request(number=1, title="title")
    diff_property = set_mock_pull_request_diff(mock_pr, github_pr_diff)

    first = ensure_revision_from_github(mock_pr)
    second = ensure_revision_from_github(mock_pr)

    assert first.pk == second.pk, "The second call should reuse the first `Revision`."
    assert Revision.objects.count() == 1, "Only one `Revision` should exist."
    assert diff_property.call_count == 1, (
        "The second call should not fetch the diff again."
    )


@pytest.mark.django_db
def test_ensure_revision_from_github_fills_patch_of_unlanded_landing_revision(
    mock_github_pull_request, github_pr_diff, diff_to_git_patch
):
    """A reused `Revision` from an unfinished pull request landing gets a `patch`.

    The landing endpoint only stores the raw `patches` on a revision, and fills `patch` in when
    the landing worker lands it. An uplift worker applies `patch`, so reusing such
    a `Revision` unchanged will fail with "Failed to parse headers from patch". In such a case,`ensure_revision_from_github` should seed from github.
    """
    mock_pr = mock_github_pull_request(number=1, title="title")
    diff_property = set_mock_pull_request_diff(mock_pr, github_pr_diff)

    landing_patch_data = {
        "author_name": "Landing Author",
        "author_email": "landing@example.com",
        "commit_message": "Bug 1 - title r=reviewer",
        "timestamp": "1761017419",
    }
    raw_patches = diff_to_git_patch(github_pr_diff)
    landing_revision = Revision.objects.create(
        pull_number=mock_pr.number,
        pull_head_sha=mock_pr.head_sha,
        pull_base_sha=mock_pr.base_sha,
        patches=raw_patches,
        patch_data=landing_patch_data,
    )

    revision = ensure_revision_from_github(mock_pr)

    assert revision.pk == landing_revision.pk, (
        "The landing endpoint's `Revision` should be reused."
    )
    assert Revision.objects.count() == 1, "No new `Revision` should be created."
    assert github_pr_diff.strip() in revision.diff, (
        "The reused `Revision` should have a parseable `patch` with the GitHub diff."
    )
    assert revision.patch_data == landing_patch_data, (
        "The landing endpoint's commit metadata should be kept."
    )
    assert revision.patches == raw_patches, (
        "The raw `patches` should be kept for the landing worker."
    )

    assert diff_property.call_count == 1, "The diff should be fetched once."


@pytest.mark.django_db
@pytest.mark.parametrize("has_landing_revision", [False, True])
def test_ensure_revision_from_github_saves_nothing_when_pull_request_changes(
    mock_github_pull_request, diff_to_git_patch, github_pr_diff, has_landing_revision
):
    """A pull request that changes while its diff is fetched saves nothing."""
    mock_pr = mock_github_pull_request(number=1, title="title")
    set_mock_pull_request_diff(
        mock_pr, PullRequest.StaleMetadataException("Head SHA changed.")
    )

    landing_revision = None
    if has_landing_revision:
        landing_revision = Revision.objects.create(
            pull_number=mock_pr.number,
            pull_head_sha=mock_pr.head_sha,
            pull_base_sha=mock_pr.base_sha,
            patches=diff_to_git_patch(github_pr_diff),
        )

    with pytest.raises(PullRequest.StaleMetadataException):
        ensure_revision_from_github(mock_pr)

    assert Revision.objects.count() == (1 if has_landing_revision else 0), (
        "No new `Revision` should be created."
    )
    if landing_revision:
        landing_revision.refresh_from_db()
        assert not landing_revision.patch, (
            "The existing revision's `patch` should be left empty."
        )
