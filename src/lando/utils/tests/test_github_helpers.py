from unittest import mock

from lando.utils.github_helpers import PullRequestPatchHelper


def test_PullRequestPatchHelper(github_api_client_pr: mock.Mock):
    # This should match the github_pr_response fixture.
    pr_url = "https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1"

    pr = github_api_client_pr.build_pull_request(1)

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
