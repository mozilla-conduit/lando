from unittest import mock

import pytest

from lando.utils.github import PullRequest
from lando.utils.github_helpers import LandoPullRequest, PullRequestPatchHelper


def test_PullRequestPatchHelper(github_api_client_pr: mock.Mock):
    # This should match the github_pr_response fixture.
    pr_url = "https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1"

    pr = LandoPullRequest.from_pr(github_api_client_pr.build_pull_request(1))

    assert pr.url == pr_url

    # Serialisation
    serialised_pr = pr.serialize()

    assert serialised_pr["url"] == pr_url

    # PatchHelper
    pr_patch_helper = PullRequestPatchHelper(pr)

    expected_commit_title = "WIP: test pull request with multiple commits"
    expected_full_commit_message = f"{expected_commit_title}\n\ntest description"

    assert pr_patch_helper.get_commit_title() == expected_commit_title
    assert pr_patch_helper.get_timestamp() == "1761017419"
    assert pr_patch_helper.parse_author_information() == (
        "Olivier Mehani",
        "omehani@mozilla.com",
    )
    assert pr_patch_helper.get_commit_description() == expected_full_commit_message, (
        "Commit description should be the full commit message"
    )

    pr_patch_helper._pr.commit_body = ""
    assert pr_patch_helper.get_commit_description() == expected_commit_title, (
        "Commit description with empty commit body should have no stray newlines"
    )


@pytest.fixture
def lando_pull_request(pull_request: PullRequest):
    return LandoPullRequest.from_pr(pull_request)


def test_pull_request_bug_ids(lando_pull_request: LandoPullRequest):
    """`LandoPullRequest.bug_ids` parses (and de-duplicates) bugs from commit messages."""
    commits = [
        {"commit": {"message": "Bug 123: do a thing"}},
        {"commit": {"message": "Bug 456 - another; bug 123 again"}},
        {"commit": {"message": "No bug: cleanup"}},
    ]
    with mock.patch.object(
        LandoPullRequest,
        "commits",
        new_callable=mock.PropertyMock,
        return_value=commits,
    ):
        assert lando_pull_request.bug_ids == {123, 456}


def test_pull_request_bugs_by_id_is_fetched_once(lando_pull_request: LandoPullRequest):
    """`bugs_by_id` caches, so the two status-flag checks share a single BMO fetch."""
    with (
        mock.patch.object(
            LandoPullRequest,
            "bug_ids",
            new_callable=mock.PropertyMock,
            return_value={123},
        ),
        mock.patch(
            "lando.utils.github_helpers.fetch_bugs", return_value={123: {"id": 123}}
        ) as fetch_bugs,
    ):
        assert lando_pull_request.bugs_by_id == {123: {"id": 123}}
        assert lando_pull_request.bugs_by_id == {123: {"id": 123}}
        assert fetch_bugs.call_count == 1, "bugs_by_id should fetch at most once"
