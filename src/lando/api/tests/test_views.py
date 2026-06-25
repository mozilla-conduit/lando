import hashlib
import hmac
import json
from unittest import mock

import pytest

from lando.main.models import Repo, SCMType
from lando.utils.github import PullRequest


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    for commit_map in commit_maps:
        response = client.get(f"/api/git2hg/git_repo/{commit_map.git_hash}")
        assert response.status_code == 200
        assert response.json() == commit_map.serialize()


@pytest.mark.django_db(transaction=True)
def test__views__hg2gitCommitMapView(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    for commit_map in commit_maps:
        response = client.get(f"/api/hg2git/git_repo/{commit_map.hg_hash}")
        assert response.status_code == 200
        assert response.json() == commit_map.serialize()


@pytest.mark.django_db(transaction=True)
def test__views__hg2gitCommitMapView_unknown_commit(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = client.get(f"/api/hg2git/git_repo/{'1' * 40}")
    assert response.status_code == 404
    assert response.json().get("error") == "No commits found"
    assert mock_catch_up.call_count == 1
    assert mock_catch_up.call_args[0] == ("git_repo",)


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_unknown_commit(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = client.get(f"/api/git2hg/git_repo/{'1' * 40}")
    assert response.status_code == 404
    assert response.json().get("error") == "No commits found"
    assert mock_catch_up.call_count == 1
    assert mock_catch_up.call_args[0] == ("git_repo",)


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_multiple_commits(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    response = client.get("/api/git2hg/git_repo/aaaaaaa")
    assert response.status_code == 400
    assert response.json().get("error") == "Multiple commits found"


@pytest.mark.django_db(transaction=True)
def test__views__git2hgCommitMapView_short_hash(commit_maps, client, monkeypatch):
    mock_catch_up = mock.MagicMock()
    monkeypatch.setattr("lando.api.views.CommitMap.catch_up", mock_catch_up)
    commit_map = commit_maps[2]
    response = client.get("/api/git2hg/git_repo/ccccccc")
    assert response.status_code == 200
    assert response.json() == commit_map.serialize()


@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend(
    phabdouble, client, user, user_phab_api_key, user_linked_to_phab, monkeypatch
):
    """Test that the Phabricator authentication backend behaves as expected."""
    response = client.get("/__version__")
    assert response.wsgi_request.user.is_anonymous

    # NOTE: due to limitations in phabdouble, the value of the token
    # is irrelevant here. This should be fixed in bug 2019413.
    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    response = client.get("/__version__", headers=headers)
    assert response.wsgi_request.user.is_authenticated


@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_unknown_phid(
    phabdouble, client, user, user_phab_api_key, monkeypatch
):
    """A valid token with no matching PHID or email should not authenticate."""
    # The phabdouble user has an email that does not match any local Django user,
    # so neither the PHID lookup nor the email fallback will find a profile.
    phabdouble.user(username="unknown_phab_user", email="unknown@example.com")

    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    response = client.get("/__version__", headers=headers)
    assert not response.wsgi_request.user.is_authenticated, (
        "A valid Phabricator token whose PHID and email do not match any local "
        "profile should not result in an authenticated request."
    )


@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_email_fallback(
    phabdouble, client, user, user_phab_api_key, monkeypatch
):
    """A valid token with no stored PHID should fall back to email and back-populate."""
    # The phabdouble user's email matches the local user, but the profile has no
    # `phabricator_phid` set. The backend should fall back to email lookup, authenticate
    # successfully, and store the PHID on the profile for future lookups.
    phab_user = phabdouble.user(username="phab_user", email=user.email)
    assert not user.profile.phabricator_phid, (
        "Profile should not have a PHID set before the email fallback test."
    )

    headers = {"X-Phabricator-API-Key": user_phab_api_key}
    response = client.get("/__version__", headers=headers)
    assert response.wsgi_request.user.is_authenticated, (
        "Email fallback should authenticate the user when the PHID is not yet stored."
    )

    user.profile.refresh_from_db()
    assert user.profile.phabricator_phid == phab_user["phid"], (
        "The backend should back-populate the PHID on the profile after email fallback."
    )


@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test__views__phabricator_auth_backend_invalid_token(
    phabdouble, client, user, user_phab_api_key, user_linked_to_phab, monkeypatch
):
    """Test that the Phabricator authentication backend behaves as expected."""
    # NOTE: Currently, PhabricatorDouble does not have any awareness of the
    # Phabricator API token being used to authorize the client. Therefore,
    # any token passed here will result in a passing test, whether it is valid
    # or not. This should be fixed (see bug 2019413.)

    headers = {"X-Phabricator-API-Key": "INVALID_TOKEN"}
    response = client.get("/__version__", headers=headers)
    assert not response.wsgi_request.user.is_authenticated


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views__pull_request_api_view__private_repo(github_api_client, client):
    mock_github_api_client = mock.MagicMock()
    mock_pr = mock.MagicMock()

    mock_github_api_client.repo_is_private = True
    mock_github_api_client.build_pull_request.return_value = mock_pr

    github_api_client.return_value = mock_github_api_client

    repo = Repo.objects.create(
        name="git-repo-private",
        url="git.example.org/mozilla-conduit/test-repo-private",
        scm_type=SCMType.GIT,
    )

    response = client.get(f"/api/pulls/{repo.name}/1/landing_jobs")
    assert response.status_code == 404

    mock_github_api_client.repo_is_private = False
    response = client.get(f"/api/pulls/{repo.name}/1/landing_jobs")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "body, expected_body",
    (
        ("this is some commit body", "this is some commit body"),
        # Extra whitespace before and after the commit message gets stripped.
        (
            "\nsomething with more characters\n\n < > <strong>test</strong> <script>\n",
            "something with more characters\n\n < > <strong>test</strong> <script>",
        ),
    ),
)
class TestViewsPullRequestUpdateWebHook:
    hmac_secret = "test secret"

    @pytest.fixture
    def hmac_headers(self):
        def calculate_signature(body=None):
            if isinstance(body, dict):
                body = json.dumps(body)
            _hmac = hmac.new(
                self.hmac_secret.encode("utf-8"),
                msg=body.encode("utf-8") or b"--BoUnDaRyStRiNg--\r\n",
                digestmod=hashlib.sha256,
            )
            return f"sha256={_hmac.hexdigest()}"

        def _headers(signature="", body=None):
            return {
                "X-Hub-Signature-256": signature or calculate_signature(body),
                "content-type": "application/json",
            }

        return _headers

    @pytest.fixture
    def webhook_gh_client(self):
        def wrapper(github_api_client, body):
            data = {
                "number": 1,
                "title": "this is some title (bug 1111111, bug 2222222)",
                "body": body,
            }
            mock_pr_data = mock.MagicMock()
            mock_pr_data.__getitem__.side_effect = lambda k: (
                data[k] if k in data else mock.MagicMock()
            )

            mock_github_api_client = mock.MagicMock()
            mock_github_api_client.repo_is_private = False

            mock_pr = PullRequest(mock_github_api_client, mock_pr_data)
            mock_github_api_client.build_pull_request.return_value = mock_pr
            github_api_client.return_value = mock_github_api_client

            repo = Repo.objects.create(
                name="git-repo",
                default_branch="test_branch",
                url="https://github.com/test-repo.git",
                scm_type=SCMType.GIT,
                pr_enabled=True,
            )
            repo.set_gh_hmac_secret(self.hmac_secret)
            return mock_github_api_client

        return wrapper

    @pytest.fixture
    def webhook_content(self):
        def _webhook_content(is_bot=False):
            return {
                "sender": {"type": "User" if not is_bot else "Bot"},
                "pull_request": {"number": 1, "base": {"ref": "test_branch"}},
                "repository": {"clone_url": "https://github.com/test-repo.git"},
            }

        return _webhook_content

    @mock.patch("lando.api.views.generate_warnings_and_blockers")
    @mock.patch("lando.api.views.GitHubAPIClient")
    @pytest.mark.django_db(transaction=True)
    def test__views__pull_request_update_webhook_no_hmac_header(
        self,
        github_api_client,
        generate_warnings_and_blockers,
        body,
        client,
        expected_body,
        webhook_gh_client,
        webhook_content,
        hmac_headers,
    ):
        """Test that the webhook fails when called without correct headers."""
        mock_github_api_client = webhook_gh_client(github_api_client, body)

        generate_warnings_and_blockers.return_value = {
            "warnings": ["a warning"],
            "blockers": ["a blocker"],
        }

        content = webhook_content()

        response = client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers={},
        )

        assert mock_github_api_client.update_pull_request_body.call_count == 0
        assert response.status_code == 403

    @mock.patch("lando.api.views.generate_warnings_and_blockers")
    @mock.patch("lando.api.views.GitHubAPIClient")
    @pytest.mark.django_db(transaction=True)
    def test__views__pull_request_update_webhook_warnings_and_blockers(
        self,
        github_api_client,
        generate_warnings_and_blockers,
        body,
        expected_body,
        client,
        webhook_gh_client,
        hmac_headers,
        webhook_content,
    ):
        """Test that the webhook is calling the GitHub API with the correct parameters."""
        mock_github_api_client = webhook_gh_client(github_api_client, body)

        generate_warnings_and_blockers.return_value = {
            "warnings": ["a warning"],
            "blockers": ["a blocker"],
        }
        content = webhook_content()
        response = client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )

        assert mock_github_api_client.update_pull_request_body.call_count == 1
        pr_number, called_body = (
            mock_github_api_client.update_pull_request_body.call_args[0]
        )
        assert pr_number == 1
        assert called_body == "\n".join(
            [
                expected_body,
                "<!--/ -+-+- DO NOT MODIFY THIS LINE - ENTER COMMIT MESSAGE ABOVE -+-+- /-->",
                "---",
                "Lando: [link](https://lando.test/pulls/git-repo/1/)",
                "Bugzilla: [bug 1111111](http://bmo.test/show_bug.cgi?id=1111111), [bug 2222222](http://bmo.test/show_bug.cgi?id=2222222)",
                "",
                "|Warnings|",
                "|---------|",
                ":warning: a warning",
                "",
                "|Blockers|",
                "|---------|",
                ":no_entry_sign: a blocker",
                "",
            ]
        )

        assert response.status_code == 200
        assert response.json() == {"status": "success"}

    @mock.patch("lando.api.views.generate_warnings_and_blockers")
    @mock.patch("lando.api.views.GitHubAPIClient")
    @pytest.mark.django_db(transaction=True)
    def test__views__pull_request_update_webhook_blockers_only(
        self,
        github_api_client,
        generate_warnings_and_blockers,
        body,
        expected_body,
        client,
        webhook_gh_client,
        hmac_headers,
        webhook_content,
    ):
        mock_github_api_client = webhook_gh_client(github_api_client, body)
        generate_warnings_and_blockers.return_value = {
            "warnings": [],
            "blockers": ["a blocker"],
        }

        content = webhook_content()
        client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )
        assert mock_github_api_client.update_pull_request_body.call_count == 1
        pr_number, called_body = (
            mock_github_api_client.update_pull_request_body.call_args[0]
        )

        assert called_body == "\n".join(
            [
                expected_body,
                "<!--/ -+-+- DO NOT MODIFY THIS LINE - ENTER COMMIT MESSAGE ABOVE -+-+- /-->",
                "---",
                "Lando: [link](https://lando.test/pulls/git-repo/1/)",
                "Bugzilla: [bug 1111111](http://bmo.test/show_bug.cgi?id=1111111), [bug 2222222](http://bmo.test/show_bug.cgi?id=2222222)",
                "",
                "|Blockers|",
                "|---------|",
                ":no_entry_sign: a blocker",
                "",
            ]
        )

    @mock.patch("lando.api.views.generate_warnings_and_blockers")
    @mock.patch("lando.api.views.GitHubAPIClient")
    @pytest.mark.django_db(transaction=True)
    def test__views__pull_request_update_webhook_no_warnings_or_blockers(
        self,
        github_api_client,
        generate_warnings_and_blockers,
        body,
        expected_body,
        client,
        webhook_gh_client,
        hmac_headers,
        webhook_content,
    ):
        mock_github_api_client = webhook_gh_client(github_api_client, body)
        generate_warnings_and_blockers.return_value = {
            "warnings": [],
            "blockers": [],
        }

        content = webhook_content()
        client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )
        assert mock_github_api_client.update_pull_request_body.call_count == 1
        pr_number, called_body = (
            mock_github_api_client.update_pull_request_body.call_args[0]
        )

        assert called_body == "\n".join(
            [
                expected_body,
                "<!--/ -+-+- DO NOT MODIFY THIS LINE - ENTER COMMIT MESSAGE ABOVE -+-+- /-->",
                "---",
                "Lando: [link](https://lando.test/pulls/git-repo/1/)",
                "Bugzilla: [bug 1111111](http://bmo.test/show_bug.cgi?id=1111111), [bug 2222222](http://bmo.test/show_bug.cgi?id=2222222)",
                ":white_check_mark: All Lando checks passed",
            ]
        )

    @mock.patch("lando.api.views.GitHubAPIClient")
    @pytest.mark.django_db(transaction=True)
    def test__views__pull_request_update_webhook_bot(
        self,
        github_api_client,
        body,
        expected_body,
        client,
        webhook_gh_client,
        hmac_headers,
        webhook_content,
    ):
        mock_github_api_client = webhook_gh_client(github_api_client, body)

        content = webhook_content(is_bot=True)
        response = client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )
        assert response.status_code == 202
        assert mock_github_api_client.update_pull_request_body.call_count == 0
