import json
from unittest import mock

import pytest

from lando.utils.github import (
    PR_DELIMITER,
    GitHub,
    GitHubAPI,
    GitHubAPIClient,
    PullRequest,
    verify_github_signature,
)


@pytest.mark.parametrize(
    "url, expected_support",
    (
        ("https://github.com/mozilla-firefox/firefox", True),
        ("https://github.com/mozilla-firefox/firefox/", True),
        ("https://someuser:somepass@github.com/owner/repo.git/", True),
        ("http://git.test/test-repo/", False),
        ("https://hg.mozilla.org/mozilla-central/", False),
    ),
)
def test_github_is_supported(url: str, expected_support: bool):
    assert GitHub.is_supported_url(url) == expected_support, (
        f"Support for {url} incorrectly determined"
    )


@pytest.mark.parametrize(
    "url, expected_repo_owner, expected_repo_name",
    (
        ("https://github.com/mozilla-firefox/firefox", "mozilla-firefox", "firefox"),
        ("https://github.com/mozilla-firefox/firefox/", "mozilla-firefox", "firefox"),
        ("https://someuser:somepass@github.com/owner/repo.git", "owner", "repo"),
        ("https://someuser:somepass@github.com/owner/repo.git/", "owner", "repo"),
    ),
)
def test_github_parsed_url(url: str, expected_repo_owner: str, expected_repo_name: str):
    github = GitHub(url)

    assert github.repo_owner == expected_repo_owner, "Repo owner mismatch"
    assert github.repo_name == expected_repo_name, "Repo name mismatch"


def test_github_parsed_url_not_github():
    with pytest.raises(ValueError):
        GitHub("https://hg.mozilla.org/mozilla-central/")


@pytest.mark.parametrize(
    "url, expected_authenticated_url",
    (
        (
            "https://github.com/mozilla-firefox/firefox/",
            "https://git:mock_token@github.com/mozilla-firefox/firefox/",
        ),
        (
            "https://github.com/mozilla-firefox/firefox.git/",
            "https://git:mock_token@github.com/mozilla-firefox/firefox.git/",
        ),
        (
            "https://github.com/mozilla-firefox/firefox.git/some?other#path",
            "https://git:mock_token@github.com/mozilla-firefox/firefox.git/some?other#path",
        ),
        (
            "https://someuser:somepass@github.com/owner/repo.git/",
            "https://someuser:somepass@github.com/owner/repo.git/",
        ),
    ),
)
def test_github_authenticated_url(
    mock_github_fetch_token: mock.Mock, url: str, expected_authenticated_url: str
):
    assert GitHub(url).authenticated_url == expected_authenticated_url


def test_github_authenticated_url_no_token(
    mock_github_fetch_token: mock.Mock, caplog: pytest.LogCaptureFixture
):
    mock_github_fetch_token.return_value = None

    url = "https://github.com/mozilla-firefox/firefox/"

    assert GitHub(url).authenticated_url == url
    assert "Couldn't obtain a token" in caplog.text


def test_github_api_init(mock_github_fetch_token: mock.Mock):
    github_api_client = GitHubAPI("https://github.com/o/r")

    assert github_api_client.session.headers.get("Authorization") == "Bearer mock_token"


def test_github_api_client_init(mock_github_fetch_token: mock.Mock):
    github_api_client = GitHubAPIClient("https://github.com/o/r")

    assert github_api_client.repo_base_url == "repos/o/r"


def test_api_client_build_pr(
    github_pr_response: str,
    github_pr_commits_response: str,
    github_pr_diff: str,
    github_pr_patch: str,
):
    github_api_client = GitHubAPIClient("https://github.com/mozilla-conduit/test-repo")

    github_api_client.get_pull_request = mock.MagicMock()
    github_api_client.get_pull_request.return_value = json.loads(github_pr_response)

    github_api_client.get_diff = mock.MagicMock()
    github_api_client.get_diff.return_value = github_pr_diff

    github_api_client.get_patch = mock.MagicMock()
    github_api_client.get_patch.return_value = github_pr_patch

    pr = github_api_client.build_pull_request(1)

    assert github_api_client.get_pull_request.call_count == 1
    assert pr.number == 1

    assert pr.diff == github_pr_diff
    assert github_api_client.get_diff.call_count == 1
    assert github_api_client.get_diff.call_args.args == (1,)

    assert pr.patch == github_pr_patch
    assert github_api_client.get_patch.call_count == 1
    assert github_api_client.get_patch.call_args.args == (1,)


@mock.patch("lando.utils.github.GitHub._fetch_token")
@mock.patch("lando.utils.github.GitHub.parse_url")
def test_api_client_get_pull_request_commits(
    parse_url: mock.Mock, fetch_token: mock.Mock
):

    parse_url.return_value = {"owner": "owner", "repo": "repo", "userinfo": ""}
    fetch_token.return_value = "token"

    github_api_client = GitHubAPIClient("https://github.example.com/owner/repo")

    github_api_client._get = mock.MagicMock()
    github_api_client._get.side_effect = [
        [{"sha": "commit_11"}, {"sha": "commit_12"}],
        [{"sha": "commit_21"}, {"sha": "commit_22"}],
        [],
    ]

    # We use list() to consume all the iterator
    commits = list(github_api_client.get_pull_request_commits(1))

    assert github_api_client._get.call_count == 3, (
        "GitHubAPIClient._get not called as many times as expected"
    )

    page = 0
    for args in github_api_client._get.call_args_list:
        assert f"?page={page}" in args[0][0], f"Incorrect page request in {args[0][0]}"
        page += 1

    assert commits == [
        {"sha": "commit_11"},
        {"sha": "commit_12"},
        {"sha": "commit_21"},
        {"sha": "commit_22"},
    ], "Unexpected commit data"


@pytest.mark.parametrize(
    "body, expected_output",
    (
        ("some random text", "some random text"),
        (
            f"some random text{PR_DELIMITER}some other text",
            "some random text",
        ),
        (
            f"some random text{PR_DELIMITER}some other text{PR_DELIMITER}more text",
            "some random text",
        ),
        ("", ""),
    ),
)
def test__PullRequest___parse_body_segments__no_delimiter(body, expected_output):
    output = PullRequest._parse_body_segments(body)
    assert output == expected_output


@pytest.mark.parametrize(
    "secret, payload, signature, is_valid",
    (
        (
            "some secret",
            b"some payload",
            "sha256=22a2e09f97e933db48ba6ef24c6be11a5a10024bd9a6a18e662e94bf3c35f257",
            True,
        ),
        ("some secret", b"some payload", "a" * 64, False),
    ),
)
def test_verify_github_signature(secret, payload, signature, is_valid):
    assert verify_github_signature(secret, payload, signature) is is_valid
