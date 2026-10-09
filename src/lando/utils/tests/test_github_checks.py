import json
from collections.abc import Callable
from unittest import mock

import pytest

from lando.api.legacy.commit_message import parse_bugs
from lando.main.models import (
    ConfigurationKey,
    ConfigurationVariable,
    Repo,
    VariableTypeChoices,
)
from lando.main.scm import SCMType
from lando.utils.github_checks import (
    PullRequestBlockingReviewsWarning,
    PullRequestFailingCheck,
    PullRequestSecurityBugStatusFlagsBlocker,
    PullRequestSecurityBugStatusFlagsUnverifiedWarning,
)
from lando.utils.github_helpers import LandoPullRequest


@pytest.fixture
def make_pull_request():
    """Return a factory building a stand-in `LandoPullRequest` for the status-flag checks.

    `commit_messages` (a `list[str]`) determines `.bug_ids` via `parse_bugs`;
    `bugs_by_id` is exposed directly as `.bugs_by_id` (a dict, or `None` to simulate
    a failed BMO fetch), mirroring the cached property both checks read. The mock is
    restricted to those two attributes so an unexpected access fails loudly.
    """

    def factory(
        *,
        commit_messages: list[str] | None = None,
        bugs_by_id: dict | None = None,
        checks: list[dict] | None = None,
        mergeable_state: LandoPullRequest.Mergeability = LandoPullRequest.Mergeability.CLEAN,
        reviews: dict | None = None,
    ) -> mock.Mock:
        commit_messages = commit_messages or ["No bug - do a thing"]

        bug_ids: set[int] = set()
        for message in commit_messages:
            bug_ids.update(parse_bugs(message))

        return mock.Mock(
            spec_set=[
                "CheckConclusion",
                "Mergeability",
                "Review",
                "bug_ids",
                "bugs_by_id",
                "checks",
                "mergeable_state",
                "reviews",
            ],
            CheckConclusion=LandoPullRequest.CheckConclusion,
            Mergeability=LandoPullRequest.Mergeability,
            Review=LandoPullRequest.Review,
            bug_ids=bug_ids,
            bugs_by_id=bugs_by_id,
            checks=checks or [],
            mergeable_state=mergeable_state,
            reviews=reviews or [],
        )

    return factory


class _NoAccess:
    """A stand-in PullRequest that fails if any attribute is read.

    Used to assert a check short-circuits (e.g. on a repo with no prefix) before
    touching the PR — in particular before triggering the `bugs_by_id` BMO fetch.
    """

    def __getattr__(self, name):
        raise AssertionError(f"unexpected access to pull_request.{name}")


def test_blocking_reviews_warning(make_pull_request):
    pr = make_pull_request(
        reviews=[
            {
                "id": 1,
                "node_id": "a",
                "user": {
                    "login": "user1",
                },
                "body": "r-\nPlease change the thing.",
                "state": "CHANGES_REQUESTED",
                "html_url": "https://github.test/org/repo/pull/1#pullrequestreview-1",
                "submitted_at": "2026-11-17T00:00:00Z",
                "commit_id": "a" * 40,
            },
            {
                "id": 2,
                "node_id": "b",
                "user": {
                    "login": "user2",
                },
                "body": "comment",
                "state": "COMMENTED",
                "html_url": "https://github.test/org/repo/pull/1#pullrequestreview-2",
                "submitted_at": "2026-11-18T00:00:00Z",
                "commit_id": "a" * 40,
            },
            {
                "id": 3,
                "node_id": "c",
                "user": {
                    "login": "user3",
                },
                "body": "r+",
                "state": "APPROVED",
                "html_url": "https://github.test/org/repo/pull/1#pullrequestreview-3",
                "submitted_at": "2026-11-19T00:00:00Z",
                "commit_id": "a" * 40,
            },
        ]
    )

    assert PullRequestBlockingReviewsWarning().run(pr, mock.Mock(), mock.Mock()) == [
        "Has a review intended to block landing. r-… (https://github.test/org/repo/pull/1#pullrequestreview-1)"
    ], "Should be warned by any CHANGES_REQUESTED review"

    pr.reviews.append(
        {
            "id": 4,
            "node_id": "d",
            "user": {
                "login": "user1",
            },
            "body": "r+",
            "state": "APPROVED",
            "html_url": "https://github.test/org/repo/pull/1#pullrequestreview-4",
            "submitted_at": "2026-11-20T00:00:00Z",
            "commit_id": "b" * 40,
        },
    )

    assert (
        PullRequestBlockingReviewsWarning().run(pr, mock.Mock(), mock.Mock()) == []
    ), (
        "Should be unwarned by a later APPROVED review by a previously change-requesting user"
    )

    pr.reviews.append(
        {
            "id": 5,
            "node_id": "d",
            "user": {
                "login": "user3",
            },
            "body": "",
            "state": "CHANGES_REQUESTED",
            "html_url": "https://github.test/org/repo/pull/1#pullrequestreview-5",
            "submitted_at": "2026-11-21T00:00:00Z",
            "commit_id": "b" * 40,
        },
    )

    assert PullRequestBlockingReviewsWarning().run(pr, mock.Mock(), mock.Mock()) == [
        "Has a review intended to block landing. (empty body)… (https://github.test/org/repo/pull/1#pullrequestreview-5)"
    ]


@pytest.mark.parametrize(
    "conclusion,failed",
    (
        (LandoPullRequest.CheckConclusion.ACTION_REQUIRED, True),
        (LandoPullRequest.CheckConclusion.CANCELLED, True),
        (LandoPullRequest.CheckConclusion.FAILURE, True),
        (LandoPullRequest.CheckConclusion.NEUTRAL, False),
        (LandoPullRequest.CheckConclusion.SUCCESS, False),
        (LandoPullRequest.CheckConclusion.SKIPPED, False),
        (LandoPullRequest.CheckConclusion.STALE, True),
        (LandoPullRequest.CheckConclusion.TIMED_OUT, False),
    ),
)
@pytest.mark.django_db
def test_pull_request_failing_check(
    make_pull_request: Callable,
    conclusion: LandoPullRequest.CheckConclusion,
    failed: bool,
):
    check_name = "some-check"

    pr = make_pull_request(
        mergeable_state=LandoPullRequest.Mergeability.UNSTABLE,
        checks=[{"name": check_name, "conclusion": conclusion}],
    )

    assert len(PullRequestFailingCheck().run(pr, mock.Mock(), mock.Mock())) == (
        1 if failed else 0
    ), f"Incorrect check warning state for {conclusion}"

    pr.mergeable_state = LandoPullRequest.Mergeability.CLEAN
    assert len(PullRequestFailingCheck().run(pr, mock.Mock(), mock.Mock())) == 0, (
        "Clean PR should never warn"
    )

    ConfigurationVariable.set(
        ConfigurationKey.GITHUB_CHECKS_LIST,
        VariableTypeChoices.JSON,
        json.dumps({"skip": [check_name]}),
    )
    pr.mergeable_state = LandoPullRequest.Mergeability.UNSTABLE
    assert len(PullRequestFailingCheck().run(pr, mock.Mock(), mock.Mock())) == 0, (
        "Skipped check should never warn"
    )


@pytest.fixture
def sec_flag_repo(repo_mc) -> Repo:
    """A Firefox-like repo with the security status-flag check enabled."""
    return repo_mc(SCMType.GIT, status_flag_prefix="cf_status_firefox")


@pytest.fixture
def no_prefix_repo(repo_mc):
    """A repo with no status-flag prefix, so the status-flag checks are disabled."""
    return repo_mc(SCMType.GIT, status_flag_prefix="")


def _run_blocker(pull_request, target_repo):
    return PullRequestSecurityBugStatusFlagsBlocker.run(pull_request, target_repo, None)


def _run_warning(pull_request, target_repo):
    return PullRequestSecurityBugStatusFlagsUnverifiedWarning.run(
        pull_request, target_repo, None
    )


@pytest.mark.django_db
def test_sec_flag_blocker_sec_high_unset_blocks(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {
        123: {
            "id": 123,
            "keywords": ["sec-high"],
            "cf_status_firefox130": "affected",
            "cf_status_firefox129": "---",
        }
    }
    result = _run_blocker(
        make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
        sec_flag_repo,
    )
    assert len(result) == 1
    assert "sec-high" in result[0]
    assert "cf_status_firefox129" in result[0]
    assert "cf_status_firefox130" not in result[0], "a set flag is not missing"


@pytest.mark.django_db
def test_sec_flag_blocker_sec_critical_message(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {
        123: {"id": 123, "keywords": ["sec-critical"], "cf_status_firefox130": "---"}
    }
    result = _run_blocker(
        make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
        sec_flag_repo,
    )
    assert result and "sec-critical" in result[0]


@pytest.mark.django_db
def test_sec_flag_blocker_all_set_passes(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {
        123: {
            "id": 123,
            "keywords": ["sec-high"],
            "cf_status_firefox130": "affected",
            "cf_status_firefox_esr128": "unaffected",
        }
    }
    assert (
        _run_blocker(
            make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
            sec_flag_repo,
        )
        == []
    )


@pytest.mark.django_db
def test_sec_flag_blocker_question_counts_as_set(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {123: {"id": 123, "keywords": ["sec-high"], "cf_status_firefox130": "?"}}
    assert (
        _run_blocker(
            make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
            sec_flag_repo,
        )
        == []
    )


@pytest.mark.django_db
def test_sec_flag_blocker_none_counts_as_unset(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {123: {"id": 123, "keywords": ["sec-high"], "cf_status_firefox130": None}}
    result = _run_blocker(
        make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
        sec_flag_repo,
    )
    assert result and "cf_status_firefox130" in result[0]


@pytest.mark.django_db
def test_sec_flag_blocker_non_security_bug_ignored(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {123: {"id": 123, "keywords": ["regression"], "cf_status_firefox130": "---"}}
    assert (
        _run_blocker(
            make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
            sec_flag_repo,
        )
        == []
    )


@pytest.mark.django_db
def test_sec_flag_blocker_repo_without_prefix_short_circuits(no_prefix_repo):
    # No prefix -> return before touching the PR (so no BMO fetch is triggered).
    assert _run_blocker(_NoAccess(), no_prefix_repo) == []


@pytest.mark.django_db
def test_sec_flag_blocker_no_bug_reference_ignored(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    assert (
        _run_blocker(
            make_pull_request(commit_messages=["No bug: cleanup"], bugs_by_id={}),
            sec_flag_repo,
        )
        == []
    )


@pytest.mark.django_db
def test_sec_flag_blocker_defers_when_bmo_unavailable(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    assert (
        _run_blocker(make_pull_request(commit_messages=["Bug 123: fix"]), sec_flag_repo)
        == []
    )


@pytest.mark.django_db
def test_sec_flag_blocker_defers_when_bug_absent(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    assert (
        _run_blocker(
            make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id={}),
            sec_flag_repo,
        )
        == []
    )


@pytest.mark.django_db
def test_sec_flag_blocker_reports_only_the_failing_bug(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {
        1: {"id": 1, "keywords": ["sec-high"], "cf_status_firefox130": "affected"},
        2: {"id": 2, "keywords": ["sec-critical"], "cf_status_firefox130": "---"},
    }
    result = _run_blocker(
        make_pull_request(commit_messages=["Bug 1, bug 2: fix"], bugs_by_id=bugs),
        sec_flag_repo,
    )
    assert len(result) == 1
    assert "Bug 2" in result[0]


@pytest.mark.django_db
def test_sec_flag_warning_when_bmo_unavailable(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    result = _run_warning(
        make_pull_request(commit_messages=["Bug 123: fix"]), sec_flag_repo
    )
    assert len(result) == 1
    assert "could not verify" in result[0]
    assert "123" in result[0]


@pytest.mark.django_db
def test_sec_flag_warning_when_bug_absent(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    result = _run_warning(
        make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id={}),
        sec_flag_repo,
    )
    assert result and "could not verify" in result[0]


@pytest.mark.django_db
def test_sec_flag_warning_collapses_multiple_unverified_bugs(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    # A BMO outage must produce a single warning listing every referenced bug id.
    result = _run_warning(
        make_pull_request(commit_messages=["Bug 1, bug 2, bug 3: fix"]), sec_flag_repo
    )
    assert len(result) == 1
    for bug_id in ("1", "2", "3"):
        assert bug_id in result[0]


@pytest.mark.django_db
def test_sec_flag_warning_silent_when_data_available(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    bugs = {
        123: {"id": 123, "keywords": ["sec-high"], "cf_status_firefox130": "affected"}
    }
    assert (
        _run_warning(
            make_pull_request(commit_messages=["Bug 123: fix"], bugs_by_id=bugs),
            sec_flag_repo,
        )
        == []
    )


@pytest.mark.django_db
def test_sec_flag_warning_repo_without_prefix_short_circuits(no_prefix_repo):
    assert _run_warning(_NoAccess(), no_prefix_repo) == []


@pytest.mark.django_db
def test_sec_flag_warning_no_bug_reference_ignored(
    make_pull_request: Callable, sec_flag_repo: Repo
):
    assert (
        _run_warning(
            make_pull_request(commit_messages=["No bug: cleanup"]), sec_flag_repo
        )
        == []
    )
