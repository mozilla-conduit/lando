import os
from datetime import datetime, timedelta
from unittest import mock

import pytest

from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.scm import SCMType
from lando.main.scm.exceptions import SCMException


@pytest.mark.parametrize(
    "scm_type",
    [
        SCMType.HG,
        SCMType.GIT,
    ],
)
@mock.patch.dict(os.environ, {LandingWorker.SSH_PRIVATE_KEY_ENV_KEY: ""})
@pytest.mark.django_db
def test_Worker__no_SSH_PRIVATE_KEY(
    caplog, landing_worker_instance, scm_type, treestatusdouble
):
    treestatusdouble.open_tree("some-tree-does-not-matter")
    # The worker will read the environment and try to handle the SSH_PRIVATE_KEY if
    # present.
    w = LandingWorker(landing_worker_instance(scm=scm_type), with_ssh=True)

    # Let the runner terminate immediately after setup.
    w.start(max_loops=-1)

    # It should complain, but continue.
    assert LandingWorker.SSH_PRIVATE_KEY_ENV_KEY in caplog.text


@pytest.fixture
def mocked_enabled_repos(get_landing_worker, monkeypatch):
    """Return a callable that sets up a landing worker for `run_idle_maintenance` tests.

    Call the returned callable with an `SCMType` to get a `(landing_worker, repos)`
    tuple for that SCM. `monkeypatch` reverts the installed mocks at the end of
    the test.

    `Worker.enabled_repos` returns a fresh QuerySet on each access, so a mock
    set on `repo._scm` doesn't survive across calls. The callable freezes the
    list once and replaces each repo's lazy SCM with a `MagicMock`.

    Also raises `sleep_seconds` so the per-call maintenance time budget isn't
    tripped by fast mocked calls, and patches `throttle` so the post-maintenance
    sleep doesn't slow the test. Individual tests may lower `sleep_seconds`
    to exercise the budget directly.
    """

    def _setup(scm_type):
        landing_worker = get_landing_worker(scm_type)
        repos = list(landing_worker.enabled_repos)
        for repo in repos:
            repo._scm = mock.MagicMock()
        landing_worker.worker_instance.sleep_seconds = 60
        monkeypatch.setattr(
            type(landing_worker),
            "enabled_repos",
            property(lambda _self: repos),
        )
        monkeypatch.setattr(landing_worker, "throttle", mock.MagicMock())
        return landing_worker, repos

    return _setup


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_run_idle_maintenance_throttles_repeat_calls(
    scm_type, mocked_enabled_repos
):
    landing_worker, repos = mocked_enabled_repos(scm_type)
    landing_worker.run_idle_maintenance()
    landing_worker.run_idle_maintenance()

    for repo in repos:
        assert repo._scm.maintenance.call_count == 1, (
            "Repeat calls inside `maintenance_interval_seconds` should be throttled."
        )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_run_idle_maintenance_runs_again_after_interval(
    scm_type, mocked_enabled_repos
):
    landing_worker, repos = mocked_enabled_repos(scm_type)
    landing_worker.run_idle_maintenance()

    # Pretend the previous run happened beyond the throttle window.
    interval = timedelta(
        seconds=landing_worker.worker_instance.maintenance_interval_seconds + 1
    )
    for repo in repos:
        landing_worker.last_maintenance_at[repo.id] -= interval

    landing_worker.run_idle_maintenance()

    for repo in repos:
        assert repo._scm.maintenance.call_count == 2, (
            "`maintenance` should run again once `maintenance_interval_seconds` has elapsed."
        )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_run_idle_maintenance_stops_at_budget_and_prefers_oldest(
    scm_type, mocked_enabled_repos
):
    """When the time budget is exhausted, stop early after processing the repo
    that has been waiting longest for maintenance."""
    landing_worker, repos = mocked_enabled_repos(scm_type)
    assert len(repos) >= 2, "Test requires at least two enabled repos."

    # A `sleep_seconds` budget of 0 means we stop after the very first repo.
    landing_worker.worker_instance.sleep_seconds = 0

    # Make every repo eligible (well past the interval) and pin one repo as the oldest.
    interval = timedelta(
        seconds=landing_worker.worker_instance.maintenance_interval_seconds + 10
    )
    now = datetime.now()
    oldest_repo = repos[-1]
    for repo in repos:
        landing_worker.last_maintenance_at[repo.id] = now - interval
    landing_worker.last_maintenance_at[oldest_repo.id] = now - (interval * 2)

    landing_worker.run_idle_maintenance()

    assert oldest_repo._scm.maintenance.call_count == 1, (
        "The repo waiting longest should run first when the budget is tight."
    )
    for repo in repos:
        if repo is oldest_repo:
            continue
        assert repo._scm.maintenance.call_count == 0, (
            "Other repos should be skipped once the budget is exhausted."
        )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_run_idle_maintenance_isolates_failures(
    caplog, scm_type, mocked_enabled_repos
):
    landing_worker, repos = mocked_enabled_repos(scm_type)
    assert len(repos) >= 2, "Test requires at least two enabled repos."

    failing_repo, *healthy_repos = repos
    failing_repo._scm.maintenance.side_effect = SCMException("boom", "", "")

    landing_worker.run_idle_maintenance()

    for repo in healthy_repos:
        repo._scm.maintenance.assert_called_once_with()
    assert f"Idle maintenance failed for {failing_repo.name}" in caplog.text, (
        "A failure in one repo's maintenance should be logged."
    )
    assert failing_repo.id in landing_worker.last_maintenance_at, (
        "A failed run should still update the timestamp so we don't retry on every idle loop."
    )
