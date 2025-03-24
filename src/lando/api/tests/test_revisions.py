import pytest

from lando.api.legacy.revisions import (
    blocker_diff_author_is_known,
    revision_is_secure,
    revision_needs_testing_tag,
)

pytestmark = pytest.mark.usefixtures("docker_env_vars")


def test_check_diff_author_is_known_with_author(phabdouble):  # noqa: ANN001
    # Adds author information by default.
    d = phabdouble.diff()
    phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert blocker_diff_author_is_known(diff=diff) is None


def test_check_diff_author_is_known_with_unknown_author(phabdouble):  # noqa: ANN001
    # No commits for no author data.
    d = phabdouble.diff(commits=[])
    phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert blocker_diff_author_is_known(diff=diff) is not None


def test_secure_api_flag_on_public_revision_is_false(
    db,  # noqa: ANN001
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    sec_approval_project,  # noqa: ANN001
    secure_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="test-repo")
    public_project = phabdouble.project("public")
    revision = phabdouble.revision(projects=[public_project], repo=repo)

    response = proxy_client.get("/stacks/D{}".format(revision["id"]))
    assert response.status_code == 200
    response_revision = response.json["revisions"].pop()
    assert not response_revision["is_secure"]


def test_secure_api_flag_on_secure_revision_is_true(
    db,  # noqa: ANN001
    proxy_client,  # noqa: ANN001
    phabdouble,  # noqa: ANN001
    release_management_project,  # noqa: ANN001
    needs_data_classification_project,  # noqa: ANN001
    sec_approval_project,  # noqa: ANN001
    secure_project,  # noqa: ANN001
):
    repo = phabdouble.repo(name="test-repo")
    revision = phabdouble.revision(projects=[secure_project], repo=repo)

    response = proxy_client.get("/stacks/D{}".format(revision["id"]))

    assert response.status_code == 200
    response_revision = response.json["revisions"].pop()
    assert response_revision["is_secure"]


def test_public_revision_is_not_secure(phabdouble, secure_project):  # noqa: ANN001
    public_project = phabdouble.project("public")
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[public_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert not revision_is_secure(revision, secure_project["phid"])


def test_secure_revision_is_secure(phabdouble, secure_project):  # noqa: ANN001
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert revision_is_secure(revision, secure_project["phid"])


def test_revision_does_not_need_testing_tag(phabdouble):  # noqa: ANN001
    testing_tag_projects = [{"phid": "testing-tag-phid"}]
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=testing_tag_projects, repo=repo)
    assert not revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_revision_needs_testing_tag(phabdouble):  # noqa: ANN001
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=[], repo=repo)
    assert revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_repo_does_not_have_testing_policy(phabdouble):  # noqa: ANN001
    repo = phabdouble.repo(projects=[])
    revision = phabdouble.revision(projects=[], repo=repo)
    assert not revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )
