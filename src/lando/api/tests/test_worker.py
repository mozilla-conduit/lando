import logging
import os
from datetime import datetime, timedelta
from unittest import mock

import pytest

from lando.api.legacy.workers.base import DEFAULT_QUEUE_SIZE_ALERT_THRESHOLD
from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.models import JobStatus, LandingJob
from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
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


@pytest.fixture
def worker_with_queue(get_landing_worker, treestatusdouble, monkeypatch):
    """Return a callable giving a landing worker and a factory for queued jobs.

    The worker's trees all start open so `active_repos` is populated. Tests that
    need a closed tree should call `treestatusdouble.close_tree` followed by
    `landing_worker.refresh_active_repos`.

    The returned factory queues `count` jobs, defaulting to the first enabled repo.
    """

    def _setup(scm_type):
        landing_worker = get_landing_worker(scm_type)
        for repo in landing_worker.enabled_repos:
            treestatusdouble.open_tree(repo.tree)
        landing_worker.refresh_active_repos()
        monkeypatch.setattr(landing_worker, "throttle", mock.MagicMock())

        def queue_jobs(count, status=JobStatus.SUBMITTED, repo=None):
            target_repo = repo or landing_worker.enabled_repos[0]
            return [
                LandingJob.objects.create(
                    status=status,
                    requester_email="tuser@example.com",
                    target_repo=target_repo,
                )
                for _ in range(count)
            ]

        return landing_worker, queue_jobs

    return _setup


def set_queue_threshold(threshold):
    """Set the queue size alert threshold configuration variable."""
    ConfigurationVariable.set(
        ConfigurationKey.WORKER_QUEUE_SIZE_ALERT_THRESHOLD,
        VariableTypeChoices.INT,
        str(threshold),
    )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_logs_size(caplog, scm_type, worker_with_queue):
    caplog.set_level(logging.INFO)
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    queue_jobs(3)

    landing_worker.log_queue_size()

    name = landing_worker.worker_instance.name
    assert (
        f"Queue size for worker {name} is 3 "
        "(3 on open trees, 0 behind closed trees)." in caplog.text
    ), "The queue size should be logged on every call."


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_counts_jobs_inside_grace_period(
    caplog, scm_type, worker_with_queue
):
    """`LandingJob.job_queue_query` can hide recently created jobs.

    The reported queue size should be the true backlog, so jobs inside the grace
    period are still counted. Note that `LANDING_WORKER_DEFAULT_GRACE_SECONDS` is
    `0` under test settings, so the grace period is passed explicitly here.
    """
    caplog.set_level(logging.INFO)
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    queue_jobs(2)

    hidden_by_grace_period = LandingJob.job_queue_query(
        repositories=landing_worker.active_repos, grace_seconds=120
    ).count()
    assert hidden_by_grace_period == 0, (
        "Jobs created just now should be hidden by a grace period."
    )

    landing_worker.log_queue_size()

    name = landing_worker.worker_instance.name
    assert f"Queue size for worker {name} is 2 " in caplog.text, (
        "Jobs inside the grace period should still count toward the queue size."
    )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_excludes_finished_jobs(
    caplog, scm_type, worker_with_queue
):
    caplog.set_level(logging.INFO)
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    queue_jobs(1)
    queue_jobs(4, status=JobStatus.LANDED)
    queue_jobs(2, status=JobStatus.CANCELLED)

    landing_worker.log_queue_size()

    name = landing_worker.worker_instance.name
    assert f"Queue size for worker {name} is 1 " in caplog.text, (
        "Only pending jobs should count toward the queue size."
    )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_splits_open_and_closed_trees(
    caplog, scm_type, worker_with_queue, treestatusdouble
):
    caplog.set_level(logging.INFO)
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    open_repo, closed_repo = list(landing_worker.enabled_repos)[:2]
    queue_jobs(2, repo=open_repo)
    queue_jobs(5, repo=closed_repo)

    treestatusdouble.close_tree(closed_repo.tree)
    landing_worker.refresh_active_repos()

    landing_worker.log_queue_size()

    name = landing_worker.worker_instance.name
    assert (
        f"Queue size for worker {name} is 7 "
        "(2 on open trees, 5 behind closed trees)." in caplog.text
    ), "Jobs behind a closed tree should be counted and reported separately."


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_warns_on_closed_tree_backlog(
    caplog, scm_type, worker_with_queue, treestatusdouble
):
    """A backlog behind a closed tree still delays landings, so it should alert."""
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    set_queue_threshold(2)
    closed_repo = landing_worker.enabled_repos[0]
    queue_jobs(3, repo=closed_repo)

    treestatusdouble.close_tree(closed_repo.tree)
    landing_worker.refresh_active_repos()

    landing_worker.log_queue_size()

    assert (
        "exceeds alert threshold: 3 (0 on open trees, 3 behind closed trees) "
        "queued, threshold is 2." in caplog.text
    ), "A queue held behind a closed tree should count toward the alert threshold."


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_ignores_other_workers_when_all_trees_closed(
    caplog, scm_type, worker_with_queue, treestatusdouble, repo_mc
):
    """An empty repo list makes `job_queue_query` drop its repo filter entirely.

    Every tree being closed must not be reported as a queue containing jobs that
    belong to some other worker.
    """
    caplog.set_level(logging.INFO)
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    for repo in landing_worker.enabled_repos:
        treestatusdouble.close_tree(repo.tree)
    landing_worker.refresh_active_repos()
    assert not landing_worker.active_repos, "Test requires every tree to be closed."

    other_worker_repo = repo_mc(scm_type=SCMType.GIT, name="some-other-workers-repo")
    queue_jobs(4, repo=other_worker_repo)

    landing_worker.log_queue_size()

    name = landing_worker.worker_instance.name
    assert (
        f"Queue size for worker {name} is 0 "
        "(0 on open trees, 0 behind closed trees)." in caplog.text
    ), "Jobs on repos this worker does not handle should never be counted."


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_warns_above_threshold(
    caplog, scm_type, worker_with_queue
):
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    set_queue_threshold(2)
    queue_jobs(3)

    landing_worker.log_queue_size()

    name = landing_worker.worker_instance.name
    assert (
        f"Queue size for worker {name} exceeds alert threshold: 3 "
        "(3 on open trees, 0 behind closed trees) queued, threshold is 2."
        in caplog.text
    ), "Exceeding the configured threshold should log a warning."


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_does_not_warn_at_threshold(
    caplog, scm_type, worker_with_queue
):
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    set_queue_threshold(3)
    queue_jobs(3)

    landing_worker.log_queue_size()

    assert "exceeds alert threshold" not in caplog.text, (
        "A queue size equal to the threshold should not warn."
    )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_log_queue_size_uses_default_threshold(
    caplog, scm_type, worker_with_queue
):
    """With no configuration variable set, `DEFAULT_QUEUE_SIZE_ALERT_THRESHOLD` applies."""
    landing_worker, queue_jobs = worker_with_queue(scm_type)
    queue_jobs(DEFAULT_QUEUE_SIZE_ALERT_THRESHOLD + 1)

    landing_worker.log_queue_size()

    assert f"threshold is {DEFAULT_QUEUE_SIZE_ALERT_THRESHOLD}." in caplog.text, (
        "The default threshold should apply when the configuration variable is unset."
    )


@pytest.mark.parametrize("scm_type", [SCMType.HG, SCMType.GIT])
@pytest.mark.django_db
def test_Worker_loop_logs_queue_size(caplog, scm_type, worker_with_queue):
    """The queue size is reported between jobs, including when the queue is empty."""
    caplog.set_level(logging.INFO)
    landing_worker, _ = worker_with_queue(scm_type)
    landing_worker.run_idle_maintenance = mock.MagicMock()

    landing_worker.loop()

    name = landing_worker.worker_instance.name
    assert f"Queue size for worker {name} is 0 " in caplog.text, (
        "`loop` should report the queue size before picking up the next job."
    )


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
