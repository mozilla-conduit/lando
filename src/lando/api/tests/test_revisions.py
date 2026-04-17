import pytest

from lando.api.legacy.api import stacks
from lando.api.legacy.revisions import (
    blocker_diff_author_is_known,
    ensure_revisions_from_phabricator,
    fetch_raw_diff_and_save,
    revision_is_secure,
    revision_needs_testing_tag,
)
from lando.main.models.revision import Revision

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


@pytest.mark.django_db
def test_fetch_raw_diff_and_save_creates_new_revision(phabdouble):
    """Creating a new `Revision` via `fetch_raw_diff_and_save`."""
    phab_revision = phabdouble.revision(title="Bug 1 - Test commit")
    phab = phabdouble.get_phabricator_client()
    diff = phabdouble.api_object_for(
        phabdouble.diff(revision=phab_revision), attachments={"commits": True}
    )

    revision = fetch_raw_diff_and_save(
        phab, phab_revision["id"], diff, "Bug 1 - Test commit"
    )

    assert (
        revision.revision_id == phab_revision["id"]
    ), "`revision_id` should match the provided value."
    assert revision.diff_id == diff["id"], "`diff_id` should match the diff."
    assert (
        revision.commit_message == "Bug 1 - Test commit"
    ), "`commit_message` should be set from the provided message."


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

    assert (
        revision.pk == existing.pk
    ), "Should update the existing Revision, not create a new one."
    assert revision.diff_id == diff["id"], "`diff_id` should be updated."
    assert (
        revision.commit_message == "Updated message"
    ), "`commit_message` should reflect the new data."


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
    assert (
        "Bug 1 - Test patch" in revision.commit_message
    ), "`commit_message` should contain the revision title."
    assert (
        "Patch summary." in revision.commit_message
    ), "`commit_message` should contain the revision summary."


@pytest.mark.django_db
def test_ensure_revisions_from_phabricator_raises_on_missing_revision(phabdouble):
    """Raises `ValueError` when a revision does not exist on Phabricator."""
    phab = phabdouble.get_phabricator_client()

    with pytest.raises(ValueError, match="not found on Phabricator"):
        ensure_revisions_from_phabricator(phab, [999999])
