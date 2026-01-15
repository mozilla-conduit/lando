import pytest

from lando.api.legacy.api import stacks
from lando.api.legacy.revisions import (
    blocker_diff_author_is_known,
    revision_is_secure,
    revision_needs_testing_tag,
)

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
