import copy
import json
from unittest import mock

import pytest
from django.core.cache import cache

from lando.api.views import PR_BASE_BRANCH_MISMATCH_BLOCKER
from lando.main.models import JobStatus, SCMType

pytestmark = pytest.mark.django_db(transaction=True)

WARNINGS_CHANGED_ERROR = (
    "The warnings present when the request was constructed have changed. "
    "Please acknowledge the new warnings and try again."
)

class StackEndpointTestBase:
    """A base class for testing stack-related endpoints."""

    @pytest.fixture(autouse=True)
    def stack_setup(self, repo_mc, repo_mc_github_api_client, authenticated_client, monkeypatch):
        self.client = authenticated_client
        self.repo = repo_mc(SCMType.GIT)
        self.github_api_client = repo_mc_github_api_client
        monkeypatch.setattr(
                "lando.api.views.GitHubAPIClient",
                mock.MagicMock(return_value=self.github_api_client),
            )

    @pytest.fixture
    def make_stack(self):
        def build(pr_specs: list[tuple[int, str]] | None = None) -> mock.MagicMock:
            stack = mock.MagicMock()
            stack.pull_requests = [
                self.make_pull_request(number, head_sha)
                for number, head_sha in (pr_specs or [(1, "aaa111"), (2, "bbb222")])
            ]
            self.github_api_client.build_stack.return_value = stack
            self.stack = stack
            return stack
        return build


    @pytest.fixture
    def mock_warnings_and_blockers(self):
        """Patch the checks, reporting no warnings and no blockers by default.

        Set `return_value` for results shared by every pull request, or `side_effect`
        for per-pull-request results in stack order.
        """
        with mock.patch(
            "lando.api.views.generate_warnings_and_blockers",
            return_value={"warnings": [], "blockers": []},
        ) as checks:
            yield checks

    @pytest.fixture
    def mock_landing_job(self, mock_warnings_and_blockers) -> dict:
        """Submit a landing job while the checks report no warnings or blockers.

        Depends on `mock_warnings_and_blockers` so the submission passes validation
        before a test reconfigures the checks.
        """
        response = self.post_landing_job()
        assert response.status_code == 201, (
            "The setup landing job should be created successfully."
        )
        return response.json()

    def make_pull_request(self, number: int, head_sha: str) -> mock.MagicMock:
        """Build a mock pull request complete enough to create a `Revision` from."""
        pull_request = mock.MagicMock()
        pull_request.number = number
        pull_request.head_sha = head_sha
        pull_request.base_sha = "base000"
        pull_request.author = ("Test User", "test@example.com")
        pull_request.reviews_summary = {}
        pull_request.commit_message = f"bug 1: pull request {number}"
        pull_request.patch = f"diff for pull request {number}"
        return pull_request

    def get_stack(self):
        return self.client.get(
            f"/api/stacks/{self.repo.name}/{self.stack_number}",
            content_type="application/json",
        )

    def get_checks(self, repo_name: str | None = None):
        return self.client.get(
            f"/api/stacks/{repo_name or self.repo.name}/{self.stack_number}/checks",
            content_type="application/json",
        )

    def get_landing_jobs(self):
        return self.client.get(
            f"/api/stacks/{self.repo.name}/{self.stack_number}/landing_jobs",
            content_type="application/json",
        )

    def get_landing_status(self):
        return self.client.get(
            f"/api/stacks/{self.repo.name}/{self.stack_number}/landing_status",
            content_type="application/json",
        )

    def post_landing_job(
        self,
        head_sha: str = "aaa123",
        base_sha: str = "bbb123",
        old_warnings: list | None = None,
    ):
        return self.client.post(
            f"/api/stacks/{self.repo.name}/{self.stack_number}/landing_jobs",
            data={
                "head_sha": head_sha,
                "base_sha": base_sha,
                "stack_number": self.stack_number,
                "old_warnings": old_warnings or [],
            },
            content_type="application/json",
        )

    def put_landing_job_status(self, status: JobStatus):
        return self.client.put(
            f"/api/stacks/{self.repo.name}/{self.stack_number}/landing_jobs",
            json.dumps({"status": status.value}),
            content_type="application/json",
        )

class TestStack(StackEndpointTestBase):
    def test_page_load_init(self, mock_warnings_and_blockers):
        self.make_stack()
        pull_requests = self.get_stack().json()["pull_requests"]
        assert pull_requests == [
            {"id": 1},
            {"id": 2},
        ], "The stack endpoint should return both pull requests."

        assert self.get_checks().json() == {
                            "bucketed_warnings": {},
                            "bucketed_blockers": {},
                            "pr_numbers": {
                                "1": {"warnings": [], "blockers": []},
                                "2": {"warnings": [], "blockers": []},
                            },
                        }, (
            "Warnings and blockers should be bucketed by message and also listed"
            " per pull request."
        )
        assert self.get_landing_jobs().json()["landing_jobs"] == [], (
            "no landing jobs should be listed for the stack when none have been submitted."
        )

    def test_page_load(
        self,
        mock_warnings_and_blockers,
    ):
        """The stack, its checks, and its landing jobs are returned correctly on page load.

        Warnings and blockers come back bucketed by message, so a message shared by
        several pull requests lists all of their numbers, and again per pull request.
        """
        self.make_stack()
        existing_landing_job = self.mock_landing_job

        expected_checks = {
        "bucketed_warnings": {"warning-1": [1, 2], "warning-2": [2]},
        "bucketed_blockers": {"blocker-1": [2]},
        "pr_numbers": {
            "1": {"warnings": ["warning-1"], "blockers": []},
            "2": {
                "warnings": ["warning-1", "warning-2"],
                "blockers": ["blocker-1"],
            },
        },
    },
        # The checks run once per pull request, in stack order, so each pull request
        # reports its own entry from `pr_numbers`.
        mock_warnings_and_blockers.side_effect = [
            expected_checks["pr_numbers"][str(pull_request.number)]
            for pull_request in self.stack.pull_requests
        ]

        pull_requests = self.get_stack().json()["pull_requests"]
        assert pull_requests == [
            {"id": 1},
            {"id": 2},
        ], "The stack endpoint should return both pull requests."

        assert self.get_checks().json() == expected_checks, (
            "Warnings and blockers should be bucketed by message and also listed"
            " per pull request."
        )

        expected_landing_jobs = [{"id": existing_landing_job["id"]}]
        assert self.get_landing_jobs().json()["landing_jobs"] == expected_landing_jobs, (
            "The stack's landing jobs should be listed on page load."
        )
        assert self.get_landing_status().json()["status"] == JobStatus.SUBMITTED, (
            "The stack's landing job should be in `SUBMITTED` status on page load."
        )

    def test_landing_job_submitted_success(self, mock_warnings_and_blockers):
        """A stack with no warnings and no blockers can request a landing.

        The user opens the stack page for two pull requests and requests a landing
        for both of them.
        """
        self.make_stack()
        response = self.post_landing_job()
        assert response.status_code == 201, (
            "Submitting a landing job should return `201`."
        )

        job_id = response.json()["id"]
        job = self.get_landing_jobs().json()["landing_jobs"][0]
        assert job["id"] == job_id, "The submitted job should be listed for the stack."
        assert self.get_landing_status().json()["status"] == JobStatus.SUBMITTED, (
            "The landing job should be in `SUBMITTED` status."
        )

    def test_landing_job_cancelled_success(self, mock_warnings_and_blockers):
        """Test that a landing job can be cancelled successfully."""
        self.make_stack()
        response = self.post_landing_job()
        assert response.status_code == 201, (
            "Submitting a landing job should return `201`."
        )

        assert self.get_landing_jobs().json()["landing_jobs"] == [{"id": response.json()["id"]}], (
            "The submitted job should be listed for the stack."
        )
        assert self.get_landing_status().json()["status"] == JobStatus.SUBMITTED, (
            "The landing job should be in `SUBMITTED` status."
        )

        response = self.put_landing_job_status(JobStatus.CANCELLED)
        assert response.status_code == 200, (
            "Cancelling the landing job should return `200`."
        )
        assert self.get_landing_jobs().json()["landing_jobs"] == [{"id": response.json()["id"]}], (
            "The cancelled job should still be listed for the stack."
        )
        assert self.get_landing_status().json()["status"] == JobStatus.CANCELLED, (
            "The landing job should be in `CANCELLED` status."
        )

    # Separate from the core endpoints; think of this as an additional feature.
    def test_checks_refresh_uses_cache(self, mock_warnings_and_blockers):
        """Checks re-run only from the first pull request with a new `head_sha`.

        The first request runs `generate_warnings_and_blockers` once per pull
        request and caches each result. A repeat request re-runs nothing. When a
        pull request's `head_sha` changes, checks re-run for that pull request
        and every one after it, while earlier results come from the cache.
        """
        cache.clear()

        self.make_stack([(1, "aaa111"), (2, "bbb222"), (3, "ccc333")])

        checks_run = mock_warnings_and_blockers
        checks_run.return_value = {"warnings": ["warning"], "blockers": ["blocker"]}

        # Every pull request reports the same single warning and blocker, so both
        # bucket to the full list of pull request numbers.
        expected_checks = {
            "bucketed_warnings": {"warning": [1, 2, 3]},
            "bucketed_blockers": {"blocker": [1, 2, 3]},
            "pr_numbers": {
                str(pull_request.number): {
                    "warnings": ["warning"],
                    "blockers": ["blocker"],
                }
                for pull_request in self.stack.pull_requests
            },
        }

        first_response = self.get_checks().json()
        assert first_response == expected_checks, (
            "The first request should return the bucketed and per-pull-request checks."
        )
        assert checks_run.call_count == len(self.stack.pull_requests), (
            "The first request should run the checks once per pull request."
        )

        second_response = self.get_checks().json()
        assert checks_run.call_count == len(self.stack.pull_requests), (
            "A repeat request should be served entirely from the cache."
        )
        assert second_response == expected_checks, (
            "The cached response should match the original response."
        )

        checks_run.reset_mock()
        self.stack.pull_requests[1].head_sha = "ddd444"
        self.get_checks()
        rechecked = [call.args[1] for call in checks_run.call_args_list]
        assert rechecked == self.stack.pull_requests[1:], (
            "A new `head_sha` on the second pull request should re-run checks"
            " for it and every pull request after it, but not the first."
        )


    @pytest.mark.parametrize(
        "page_load_warnings, landing_warnings, expected_status",
        [
            (
                {"1": [], "2": []},
                {"1": [], "2": []},
                201,
            ),
            (
                {"1": ["warning-1"], "2": ["warning-1", "warning-2"]},
                {"1": ["warning-1"], "2": ["warning-1", "warning-2"]},
                201,
            ),
            (
                {"1": [], "2": []},
                {"1": [], "2": ["warning-1"]},
                400,
            ),
            (
                {"1": ["warning-1"], "2": ["warning-2"]},
                {"1": [], "2": []},
                400,
            ),
            (
                {"1": ["warning-1"], "2": ["warning-2"]},
                {"1": ["warning-1"], "2": ["warning-3"]},
                400,
            ),
        ],
    )
    def test_landing_job_warnings_mismatch(
        self,
        mock_warnings_and_blockers,
        page_load_warnings,
        landing_warnings,
        expected_status,
    ):
        """A stack lands only when the acknowledged warnings still match the current ones.

        The user fetches the checks on page load, acknowledges the warnings, and sends
        them back with the landing request organized per pull request, the same way
        `pr_numbers` organizes them. The landing is rejected if any pull request's
        warnings changed between the page load and the landing request.
        """
        # The checks run once per pull request for the page load `GET`, then once per
        # pull request again for the landing `POST`.
        self.make_stack()

        mock_warnings_and_blockers.side_effect = [
            {"warnings": page_load_warnings[str(pull_request.number)], "blockers": []}
            for pull_request in self.stack.pull_requests
        ] + [
            {"warnings": landing_warnings[str(pull_request.number)], "blockers": []}
            for pull_request in self.stack.pull_requests
        ]

        checks = self.get_checks().json()
        old_warnings = {
            number: pull_request_checks["warnings"]
            for number, pull_request_checks in checks["pr_numbers"].items()
        }
        assert old_warnings == page_load_warnings, (
            "The checks endpoint should report the page load warnings per pull request."
        )

        response = self.post_landing_job(old_warnings=old_warnings)

        assert response.status_code == expected_status, (
            "The landing should be accepted only when the warnings have not changed."
        )

        if expected_status == 400:
            assert response.json()["errors"] == {
                "warnings": [WARNINGS_CHANGED_ERROR]
            }, "The response should report that the warnings have changed."
            assert response.json()["new_warnings"] == landing_warnings, (
                "The response should return the current warnings per pull request so"
                " the user can acknowledge them."
            )
            assert self.get_landing_status().json()["status"] is None, (
                "No landing job should be created while warnings are unacknowledged."
            )
        else:
            assert self.get_landing_status().json()["status"] == JobStatus.SUBMITTED, (
                "The landing job should be in `SUBMITTED` status."
            )

    def test_branch_mismatch_blocker_stripped(self, mock_warnings_and_blockers):
        """The branch mismatch blocker is stripped from the checks and landing request.

        Every pull request in a stack except the first sits on another pull request's
        branch rather than the target branch, so the mismatch blocker is expected
        there. It is not meant to be acknowledged by the user, so it is stripped from
        the checks response and does not block the landing request.
        """
        self.make_stack()

        unstripped_checks = [
            {"warnings": [], "blockers": []},
            {
                "warnings": ["warning-1"],
                "blockers": [PR_BASE_BRANCH_MISMATCH_BLOCKER],
            },
        ]

        # The checks run once per pull request.
        mock_warnings_and_blockers.side_effect = copy.deepcopy(unstripped_checks)

        checks = self.get_checks().json()
        assert checks == {
            "bucketed_warnings": {"warning-1": [2]},
            "bucketed_blockers": {},
            "pr_numbers": {
                "1": {"warnings": [], "blockers": []},
                "2": {"warnings": ["warning-1"], "blockers": []},
            },
        }, (
            "The mismatch blocker on a later pull request should be stripped from the"
            " checks response entirely, while other warnings are reported as usual."
        )

        mock_warnings_and_blockers.side_effect = copy.deepcopy(unstripped_checks)

        old_warnings = {
            number: pull_request_checks["warnings"]
            for number, pull_request_checks in checks["pr_numbers"].items()
        }
        response = self.post_landing_job(old_warnings=old_warnings)

        assert response.status_code == 201, (
            "The mismatch blocker on a later pull request should not block the landing."
        )
        assert self.get_landing_status().json()["status"] == JobStatus.SUBMITTED, (
            "The landing job should be in `SUBMITTED` status."
        )
