import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.test import Client

from lando.main.models import JobStatus, Repo, SCMType
from lando.main.models.landing_job import LandingJob, add_revisions_to_job
from lando.main.models.revision import Revision


@pytest.fixture
def repo_mc_github_api_client(repo_mc):
    repo_mc(SCMType.GIT, name="git-repo")

    mock_github_api_client = mock.MagicMock()
    mock_github_api_client.repo_is_private = False
    return mock_github_api_client


@pytest.fixture
def csrf_client(user, user_plaintext_password):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.login(username=user.username, password=user_plaintext_password)
    return csrf_client


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


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "payload, expected_status, expected_response",
    [
        (
            {
                "title": "Valid New Title",
                "body": "Valid New Body",
            },
            204,
            b"",
        ),
        (
            {
                "title": "",
                "body": "Valid New Body",
            },
            400,
            {
                "title": ["This field is required."],
            },
        ),
        (
            {
                "title": "a" * 300,
                "body": "Valid New Body",
            },
            400,
            {
                "title": ["Ensure this value has at most 256 characters (it has 300)."],
            },
        ),
    ],
)
def test__views__pull_request_content_api_view(
    github_api_client,
    authenticated_client,
    repo_mc_github_api_client,
    payload,
    expected_status,
    expected_response,
):
    """Test PullRequestContentAPIView validation and success responses."""

    github_api_client.return_value = repo_mc_github_api_client

    mock_pull_request = mock.MagicMock()

    repo_mc_github_api_client.build_pull_request.return_value = mock_pull_request
    repo_mc_github_api_client.update_pull_request_content.return_value = payload

    result = authenticated_client.put(
        "/api/pulls/git-repo/100",
        data=payload,
        content_type="application/json",
    )

    assert result.status_code == expected_status

    if expected_status == 204:
        assert result.content == expected_response
    else:
        response_json = result.json()
        for key, value in expected_response.items():
            assert response_json.get(key) == value


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views__pull_request_content_api_view__unauthenticated(
    github_api_client, client, repo_mc_github_api_client
):
    """An anonymous PUT should be rejected by the auth decorator."""

    github_api_client.return_value = repo_mc_github_api_client

    result = client.put(
        "/api/pulls/git-repo/100",
        data={"title": "Valid New Title", "body": "Valid New Body"},
        content_type="application/json",
    )

    # return 403 instead of 401 due to bug with django auth decorator. See: https://github.com/django/django/blob/main/django/core/handlers/exception.py#L75C51-L75C54
    assert result.status_code == 403
    assert b"403 Forbidden" in result.content


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
def test__views__pull_request_content_api_view__missing_csrf_token(
    github_api_client, csrf_client, repo_mc_github_api_client
):
    """An authenticated PUT without a CSRF token should be rejected."""
    github_api_client.return_value = repo_mc_github_api_client

    result = csrf_client.put(
        "/api/pulls/git-repo/100",
        data={"title": "Valid New Title", "body": "Valid New Body"},
        content_type="application/json",
    )
    assert result.status_code == 403
    assert b"403 Forbidden" in result.content


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
        def wrapper(github_api_client):
            mock_github_api_client = mock.MagicMock()
            mock_github_api_client.repo_is_private = False
            github_api_client.return_value = mock_github_api_client

            repo = Repo.objects.create(
                name="git-repo",
                default_branch="test_branch",
                url="https://example.org/test-org/test-repo.git",
                scm_type=SCMType.GIT,
                pr_enabled=True,
            )
            repo.set_gh_hmac_secret(self.hmac_secret)
            return mock_github_api_client

        return wrapper

    @pytest.fixture
    def webhook_content(self, pull_request_data, update_dict):
        def _webhook_content(is_bot=False, overrides=None):
            data = {
                "sender": {"type": "User" if not is_bot else "Bot"},
                "pull_request": pull_request_data(
                    **{
                        "number": 1,
                        "base": {
                            "ref": "test_branch",
                            "repo": {
                                "clone_url": "https://example.org/test-org/test-repo.git"
                            },
                        },
                    }
                ),
            }

            if overrides:
                update_dict(data, overrides)

            return data

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
        content = webhook_content(overrides={"pull_request": {"body": body}})
        mock_github_api_client = webhook_gh_client(github_api_client)

        generate_warnings_and_blockers.return_value = {
            "warnings": ["a warning"],
            "blockers": ["a blocker"],
        }

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
        content = webhook_content(overrides={"pull_request": {"body": body}})
        mock_github_api_client = webhook_gh_client(github_api_client)

        generate_warnings_and_blockers.return_value = {
            "warnings": ["a warning", "another warning"],
            "blockers": ["a blocker", "another blocker", "and a third one"],
        }
        response = client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )

        assert mock_github_api_client.update_pull_request_content.call_count == 1
        pr_number, called_body = (
            mock_github_api_client.update_pull_request_content.call_args[0]
        )
        assert pr_number == 1
        assert called_body == "\n".join(
            [
                expected_body,
                "<!--/ -+-+- DO NOT MODIFY THIS LINE - ENTER COMMIT MESSAGE ABOVE -+-+- /-->",
                "",
                "---",
                "",
                "Lando: [link](https://lando.test/pulls/git-repo/1/)",
                "Bugzilla: [bug 1111111](http://bmo.test/show_bug.cgi?id=1111111), [bug 2222222](http://bmo.test/show_bug.cgi?id=2222222)",
                "",
                ":warning: This pull request has 2 warnings.",
                ":no_entry_sign: This pull request has 3 blockers.",
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
        content = webhook_content(overrides={"pull_request": {"body": body}})
        mock_github_api_client = webhook_gh_client(github_api_client)
        generate_warnings_and_blockers.return_value = {
            "warnings": [],
            "blockers": ["a blocker"],
        }

        client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )
        assert mock_github_api_client.update_pull_request_content.call_count == 1
        pr_number, called_body = (
            mock_github_api_client.update_pull_request_content.call_args[0]
        )

        assert called_body == "\n".join(
            [
                expected_body,
                "<!--/ -+-+- DO NOT MODIFY THIS LINE - ENTER COMMIT MESSAGE ABOVE -+-+- /-->",
                "",
                "---",
                "",
                "Lando: [link](https://lando.test/pulls/git-repo/1/)",
                "Bugzilla: [bug 1111111](http://bmo.test/show_bug.cgi?id=1111111), [bug 2222222](http://bmo.test/show_bug.cgi?id=2222222)",
                "",
                ":no_entry_sign: This pull request has 1 blocker.",
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
        content = webhook_content(overrides={"pull_request": {"body": body}})
        mock_github_api_client = webhook_gh_client(github_api_client)
        generate_warnings_and_blockers.return_value = {
            "warnings": [],
            "blockers": [],
        }

        client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )
        assert mock_github_api_client.update_pull_request_content.call_count == 1
        pr_number, called_body = (
            mock_github_api_client.update_pull_request_content.call_args[0]
        )

        assert called_body == "\n".join(
            [
                expected_body,
                "<!--/ -+-+- DO NOT MODIFY THIS LINE - ENTER COMMIT MESSAGE ABOVE -+-+- /-->",
                "",
                "---",
                "",
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
        content = webhook_content(
            overrides={"pull_request": {"body": body}}, is_bot=True
        )
        mock_github_api_client = webhook_gh_client(github_api_client)
        response = client.post(
            "/api/pulls/webhook",
            content,
            content_type="application/json",
            headers=hmac_headers(body=content),
        )
        assert response.status_code == 202
        assert mock_github_api_client.update_pull_request_body.call_count == 0


@mock.patch("lando.api.views.generate_warnings_and_blockers")
@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "warnings_1, warnings_2, expected_status, expected_response",
    [
        ([], [], 201, b""),
        (["warning-1", "warning-2"], ["warning-1", "warning-2"], 201, b""),
        (
            [],
            ["warning-1", "warning-2"],
            400,
            [
                "The warnings present when the request was constructed have changed. Please acknowledge the new warnings and try again."
            ],
        ),
        (
            ["warning-1", "warning-2"],
            [],
            400,
            [
                "The warnings present when the request was constructed have changed. Please acknowledge the new warnings and try again."
            ],
        ),
        (
            ["warning-1", "warning-2"],
            ["warning-3", "warning-4"],
            400,
            [
                "The warnings present when the request was constructed have changed. Please acknowledge the new warnings and try again."
            ],
        ),
    ],
)
def test__views_landing_job_pull_request_view__warnings(
    github_api_client,
    mock_warnings_and_blockers,
    authenticated_client,
    repo_mc_github_api_client,
    repo_mc,
    warnings_1,
    warnings_2,
    expected_status,
    expected_response,
):
    repo = repo_mc(SCMType.GIT)
    github_api_client.return_value = repo_mc_github_api_client

    mock_pr = mock.MagicMock()
    repo_mc_github_api_client.build_pull_request.return_value = mock_pr
    mock_pr.author = ("Test Author", "test@email.com")
    mock_pr.commit_message = "Test Commit Message"
    mock_pr.number = 1
    mock_pr.head_sha = "aaa123"
    mock_pr.base_sha = "bbb123"
    mock_pr.patch = "diff --git a/abc b/def\n"
    mock_pr.reviews_summary = {}

    mock_warnings_and_blockers.return_value = {
        "warnings": warnings_1,
        "blockers": [],
    }

    old_warnings = authenticated_client.get(
        f"/api/pulls/{repo.name}/1/checks",
        content_type="application/json",
    ).json()["warnings"]

    mock_warnings_and_blockers.return_value = {
        "warnings": warnings_2,
        "blockers": [],
    }

    response = authenticated_client.post(
        f"/api/pulls/{repo.name}/1/landing_jobs",
        data={
            "head_sha": "aaa123",
            "base_sha": "bbb123",
            "pull_number": 1,
            "old_warnings": old_warnings,
        },
        content_type="application/json",
    )

    assert response.status_code == expected_status
    if expected_status == 400:
        new_warnings = response.json()["new_warnings"]

        assert new_warnings == mock_warnings_and_blockers.return_value["warnings"]
        assert response.json()["errors"] == {"warnings": expected_response}


@mock.patch("lando.api.views.GitHubAPIClient")
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "job_status,expected_status",
    [
        (JobStatus.LANDED, "landed"),
        (JobStatus.SUBMITTED, "submitted"),
        (JobStatus.FAILED, "failed"),
        (JobStatus.ABORTED, "aborted"),
    ],
)
def test__views__landing_job_pull_request_view__status(
    github_api_client,
    client,
    repo_mc_github_api_client,
    repo_mc,
    job_status,
    expected_status,
):
    """Every job status is reported for the pull request."""
    repo = repo_mc(SCMType.GIT)
    github_api_client.return_value = repo_mc_github_api_client

    pull_number = 1
    repo_mc_github_api_client.build_pull_request.return_value = mock.MagicMock(
        number=pull_number
    )

    job = LandingJob.objects.create(
        target_repo=repo, status=job_status, is_pull_request_job=True
    )
    add_revisions_to_job([Revision.objects.create(pull_number=pull_number)], job)

    response = client.get(f"/api/pulls/{repo.name}/{pull_number}/landing_jobs")

    assert response.json() == {"status": expected_status}, (
        f"A `{job_status}` job should be reported as `{expected_status}`."
    )
