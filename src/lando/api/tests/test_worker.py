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
def mocked_enabled_repos(hg_landing_worker):
    """Configure `hg_landing_worker` for `run_idle_maintenance` tests.

    `Worker.enabled_repos` returns a fresh QuerySet on each access, so a mock
    set on `repo._scm` doesn't survive across calls. This fixture freezes the
    list once and replaces each repo's lazy SCM with a `MagicMock`.

    Also raises `sleep_seconds` so the per-call maintenance time budget isn't
    tripped by fast mocked calls, and patches `throttle` so the post-maintenance
    sleep doesn't slow the test. Individual tests may lower `sleep_seconds`
    to exercise the budget directly.
    """
    repos = list(hg_landing_worker.enabled_repos)
    for repo in repos:
        repo._scm = mock.MagicMock()
    hg_landing_worker.worker_instance.sleep_seconds = 60
    with (
        mock.patch.object(
            type(hg_landing_worker), "enabled_repos", new_callable=mock.PropertyMock
        ) as mock_enabled,
        mock.patch.object(hg_landing_worker, "throttle"),
    ):
        mock_enabled.return_value = repos
        yield repos


@pytest.mark.django_db
def test_Worker_run_idle_maintenance_throttles_repeat_calls(
    hg_landing_worker, mocked_enabled_repos
):
    hg_landing_worker.run_idle_maintenance()
    hg_landing_worker.run_idle_maintenance()

    for repo in mocked_enabled_repos:
        assert repo._scm.maintenance.call_count == 1, (
            "Repeat calls inside `maintenance_interval_seconds` should be throttled."
        )


@pytest.mark.django_db
def test_Worker_run_idle_maintenance_runs_again_after_interval(
    hg_landing_worker, mocked_enabled_repos
):
    hg_landing_worker.run_idle_maintenance()

    # Pretend the previous run happened beyond the throttle window.
    interval = timedelta(
        seconds=hg_landing_worker.worker_instance.maintenance_interval_seconds + 1
    )
    for repo in mocked_enabled_repos:
        hg_landing_worker.last_maintenance_at[repo.id] -= interval

    hg_landing_worker.run_idle_maintenance()

    for repo in mocked_enabled_repos:
        assert repo._scm.maintenance.call_count == 2, (
            "`maintenance` should run again once `maintenance_interval_seconds` has elapsed."
        )


@pytest.mark.django_db
def test_Worker_run_idle_maintenance_stops_at_budget_and_prefers_oldest(
    hg_landing_worker, mocked_enabled_repos
):
    """When the time budget is exhausted, stop early after processing the repo
    that has been waiting longest for maintenance."""
    assert len(mocked_enabled_repos) >= 2, "Test requires at least two enabled repos."

    # A `sleep_seconds` budget of 0 means we stop after the very first repo.
    hg_landing_worker.worker_instance.sleep_seconds = 0

    # Make every repo eligible (well past the interval) and pin one repo as the oldest.
    interval = timedelta(
        seconds=hg_landing_worker.worker_instance.maintenance_interval_seconds + 10
    )
    now = datetime.now()
    oldest_repo = mocked_enabled_repos[-1]
    for repo in mocked_enabled_repos:
        hg_landing_worker.last_maintenance_at[repo.id] = now - interval
    hg_landing_worker.last_maintenance_at[oldest_repo.id] = now - (interval * 2)

    hg_landing_worker.run_idle_maintenance()

    assert oldest_repo._scm.maintenance.call_count == 1, (
        "The repo waiting longest should run first when the budget is tight."
    )
    for repo in mocked_enabled_repos:
        if repo is oldest_repo:
            continue
        assert repo._scm.maintenance.call_count == 0, (
            "Other repos should be skipped once the budget is exhausted."
        )


@pytest.mark.django_db
def test_Worker_run_idle_maintenance_isolates_failures(
    caplog, hg_landing_worker, mocked_enabled_repos
):
    assert len(mocked_enabled_repos) >= 2, "Test requires at least two enabled repos."

    failing_repo, *healthy_repos = mocked_enabled_repos
    failing_repo._scm.maintenance.side_effect = SCMException("boom", "", "")

    hg_landing_worker.run_idle_maintenance()

    for repo in healthy_repos:
        repo._scm.maintenance.assert_called_once_with()
    assert f"Idle maintenance failed for {failing_repo.name}" in caplog.text, (
        "A failure in one repo's maintenance should be logged."
    )
    assert failing_repo.id in hg_landing_worker.last_maintenance_at, (
        "A failed run should still update the timestamp so we don't retry on every idle loop."
    )
