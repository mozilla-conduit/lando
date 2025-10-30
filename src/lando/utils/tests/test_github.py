from unittest import mock

import pytest

from lando.utils.github import GitHub, GitHubAPI, GitHubAPIClient


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
    assert (
        GitHub.is_supported_url(url) == expected_support
    ), f"Support for {url} incorrectly determined"


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


@pytest.fixture
def mock_github_fetch_token(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    mock_fetch_token = mock.MagicMock()
    mock_fetch_token.return_value = "token"
    monkeypatch.setattr("lando.utils.github.GitHub._fetch_token", mock_fetch_token)
    return mock_fetch_token


@pytest.mark.parametrize(
    "url, expected_authenticated_url",
    (
        (
            "https://github.com/mozilla-firefox/firefox/",
            "https://git:token@github.com/mozilla-firefox/firefox",
        ),
        (
            "https://someuser:somepass@github.com/owner/repo.git/",
            "https://someuser:somepass@github.com/owner/repo",
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

    assert GitHub(url).authenticated_url == url.removesuffix("/")
    assert "Couldn't obtain a token" in caplog.text


def test_github_api_init(mock_github_fetch_token: mock.Mock):
    api_client = GitHubAPI("https://github.com/o/r")

    assert api_client.session.headers.get("Authorization") == "Bearer token"


def test_github_api_client_init(mock_github_fetch_token: mock.Mock):
    api_client = GitHubAPIClient("https://github.com/o/r")

    assert api_client.repo_base_url == "repos/o/r"
