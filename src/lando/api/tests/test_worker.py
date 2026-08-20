import logging
import os
from datetime import datetime, timedelta
from unittest import mock

import pytest

from lando.api.legacy.workers.base import (
    DEFAULT_QUEUE_SIZE_ALERT_THRESHOLD,
    QueueSize,
    Worker,
)
from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.models import JobStatus
from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
from lando.main.scm import SCMType
from lando.main.scm.exceptions import SCMException
from lando.treestatus.models import TreeStatus


@pytest.mark.parametrize(
    "scm_type",
    [
        SCMType.HG,
        SCMType.GIT,
    ],
)
@mock.patch.dict(os.environ, {LandingWorker.SSH_PRIVATE_KEY_ENV_KEY: ""})
@pytest.mark.django_db
def test_Worker__no_SSH_PRIVATE_KEY(caplog, landing_worker_instance, scm_type):
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
def worker_with_open_trees(git_landing_worker):
    """Return a landing worker whose enabled repos all have open trees.

    A repo without a tree in Treestatus is considered open, so tests that need a
    closed tree create one with `new_treestatus_tree` followed by
    `landing_worker.refresh_active_repos`.
    """
    git_landing_worker.refresh_active_repos()
    return git_landing_worker


@pytest.fixture
def bulk_add_landing_jobs(make_landing_job):
    """Return a callable that adds `count` landing jobs against a repo."""

    def _bulk_add(repo, count, status=JobStatus.SUBMITTED):
        for _ in range(count):
            make_landing_job(status=status, target_repo=repo)

    return _bulk_add


@pytest.fixture
def set_queue_threshold():
    """Return a callable that sets the queue size alert threshold."""

    def _set(threshold):
        ConfigurationVariable.set(
            ConfigurationKey.WORKER_QUEUE_SIZE_ALERT_THRESHOLD,
            VariableTypeChoices.INT,
            str(threshold),
        )

    return _set


@pytest.fixture
def worker_stub():
    """Return a callable building a `Worker` stand-in, for testing without a DB."""

    def _stub(name="test-worker"):
        stub = mock.MagicMock()
        stub.worker_instance.name = name
        return stub

    return _stub


def test_QueueSize_totals_open_and_closed_trees():
    queue_size = QueueSize(open_trees=74, closed_trees=5)

    assert queue_size.total == 79, "`total` should sum both tallies."
    assert str(queue_size) == "79 (74 on open trees, 5 behind closed trees)", (
        "A `QueueSize` should describe its own breakdown."
    )
    assert queue_size.log_fields == {
        "queue_size": 79,
        "open_queue_size": 74,
        "closed_queue_size": 5,
    }, "Each tally should be available as a separate log field for metrics."


def test_Worker_log_queue_size_logs_size(caplog, worker_stub):
    caplog.set_level(logging.INFO)

    Worker.log_queue_size(worker_stub("try"), QueueSize(open_trees=74, closed_trees=5))

    assert (
        "Queue size for worker try is 79 "
        "(74 on open trees, 5 behind closed trees)." in caplog.text
    ), "The queue size and its breakdown should be logged."


def test_Worker_log_queue_size_logs_at_the_given_level(caplog, worker_stub):
    caplog.set_level(logging.INFO)

    Worker.log_queue_size(
        worker_stub("try"), QueueSize(open_trees=74, closed_trees=5), logging.WARNING
    )

    assert [record.levelno for record in caplog.records] == [logging.WARNING], (
        "The queue size should be logged once, at the requested level."
    )


def test_Worker_queue_size_without_enabled_repos_counts_nothing(worker_stub):
    """`job_queue_query` drops its repo filter entirely for an empty repo list."""
    stub = worker_stub()
    stub.enabled_repos = []

    assert Worker.queue_size(stub) == QueueSize(), (
        "A worker with no enabled repos should have an empty queue."
    )
    assert not stub.job_type.job_queue_query.called, (
        "The queue must not be counted without a repo filter, which would pick up "
        "every other worker's jobs."
    )


@pytest.mark.django_db
def test_Worker_queue_size_splits_open_and_closed_trees(
    worker_with_open_trees, new_treestatus_tree, bulk_add_landing_jobs
):
    """Only pending jobs count, tallied by whether their tree is open."""
    open_repo, closed_repo = list(worker_with_open_trees.enabled_repos)[:2]
    bulk_add_landing_jobs(open_repo, 2)
    bulk_add_landing_jobs(open_repo, 1, status=JobStatus.DEFERRED)
    bulk_add_landing_jobs(open_repo, 1, status=JobStatus.LANDED)
    bulk_add_landing_jobs(open_repo, 1, status=JobStatus.CANCELLED)
    bulk_add_landing_jobs(closed_repo, 4)

    new_treestatus_tree(tree=closed_repo.tree, status=TreeStatus.CLOSED)
    worker_with_open_trees.refresh_active_repos()

    assert worker_with_open_trees.queue_size() == QueueSize(
        open_trees=3, closed_trees=4
    ), "Pending jobs should be tallied by tree state, ignoring finished jobs."


@pytest.mark.django_db
def test_Worker_queue_size_alert_threshold_defaults(
    git_landing_worker, set_queue_threshold
):
    assert git_landing_worker.queue_size_alert_threshold == (
        DEFAULT_QUEUE_SIZE_ALERT_THRESHOLD
    ), "The default should apply when the configuration variable is unset."

    set_queue_threshold(5)

    assert git_landing_worker.queue_size_alert_threshold == 5, (
        "The configuration variable should override the default."
    )


@pytest.mark.parametrize(
    ("queued", "threshold", "warns"),
    [(0, 25, False), (3, 3, False), (3, 2, True)],
    ids=["empty-queue", "at-threshold", "above-threshold"],
)
@pytest.mark.django_db
def test_Worker_loop_reports_queue_size(
    caplog,
    worker_with_open_trees,
    bulk_add_landing_jobs,
    set_queue_threshold,
    queued,
    threshold,
    warns,
):
    """`loop` logs the size every time, and warns only once it passes the threshold."""
    caplog.set_level(logging.INFO)
    worker_with_open_trees.run_idle_maintenance = mock.MagicMock()
    worker_with_open_trees.run_job = mock.MagicMock(return_value=True)
    set_queue_threshold(threshold)
    bulk_add_landing_jobs(worker_with_open_trees.enabled_repos[0], queued)

    worker_with_open_trees.loop()

    name = worker_with_open_trees.worker_instance.name
    queue_records = [
        record
        for record in caplog.records
        if record.getMessage().startswith(f"Queue size for worker {name} is {queued} ")
    ]

    assert len(queue_records) == 1, (
        "`loop` should report the queue size once before picking up the next job."
    )
    assert queue_records[0].levelno == (logging.WARNING if warns else logging.INFO), (
        "`loop` should log the queue size as a warning only once it passes the "
        "threshold."
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
