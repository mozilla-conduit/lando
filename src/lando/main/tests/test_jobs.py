from typing import Callable

import pytest

from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
from lando.main.models.jobs import (
    ABORTED_ERROR_TEMPLATE,
    DEFAULT_MAX_JOB_ATTEMPTS,
    JobAction,
    JobStatus,
)
from lando.main.models.landing_job import LandingJob
from lando.main.models.uplift import UpliftJob


@pytest.mark.parametrize(
    "job_class,expected_path",
    (
        (LandingJob, "/landings/1/"),
        (AutomationJob, "/api/jobs/1/"),
        (UpliftJob, "/uplift/jobs/1/"),
    ),
)
def test__models__BaseJob__url(job_class: type, expected_path: str):
    job = job_class(id=1, status=JobStatus.SUBMITTED)
    assert job.url() == f"https://lando.test{expected_path}", (
        f"`url` should point at the details page of the {job.type} job."
    )


def attempt_and_defer(job: LandingJob, times: int):
    """Attempt and defer `job` `times` times, as the worker would."""
    for attempt in range(times):
        job.start_attempt()
        job.transition_status(JobAction.DEFER, message=f"failure {attempt}")


@pytest.mark.django_db
def test__models__BaseJob__has_attempts_remaining(make_landing_job: Callable):
    job = make_landing_job(status=JobStatus.SUBMITTED)

    attempt_and_defer(job, DEFAULT_MAX_JOB_ATTEMPTS - 1)
    assert job.has_attempts_remaining(), (
        "A job below the maximum number of attempts should have attempts remaining."
    )

    attempt_and_defer(job, 1)
    assert not job.has_attempts_remaining(), (
        "A job at the maximum number of attempts should have no attempts remaining."
    )


@pytest.mark.django_db
def test__models__BaseJob__abort_sets_templated_error(make_landing_job: Callable):
    job = make_landing_job(status=JobStatus.IN_PROGRESS, attempts=3)

    job.transition_status(JobAction.ABORT, message="the last failure")

    assert job.status == JobStatus.ABORTED, "`ABORT` should abort the job."
    assert job.error == ABORTED_ERROR_TEMPLATE.format(
        attempts=3, message="the last failure"
    ), "The error should explain the abort and quote the last failure verbatim."


@pytest.mark.parametrize("max_attempts", (1, 2, 5))
@pytest.mark.django_db
def test__models__BaseJob__max_attempts_configuration(
    make_landing_job: Callable,
    max_attempts: int,
):
    ConfigurationVariable.set(
        ConfigurationKey.MAX_JOB_ATTEMPTS, VariableTypeChoices.INT, str(max_attempts)
    )
    job = make_landing_job(status=JobStatus.SUBMITTED)

    assert job.max_attempts == max_attempts, (
        "`MAX_JOB_ATTEMPTS` should be used instead of the default."
    )

    attempt_and_defer(job, max_attempts - 1)

    assert job.has_attempts_remaining(), (
        "The job should have attempts remaining before its last allowed attempt."
    )

    attempt_and_defer(job, 1)

    assert not job.has_attempts_remaining(), (
        "The job should have no attempts remaining after its last allowed attempt."
    )


@pytest.mark.django_db
def test__models__BaseJob__transition_status_rejects_unknown_params(
    make_landing_job: Callable,
):
    job = make_landing_job(status=JobStatus.SUBMITTED)

    with pytest.raises(ValueError):
        job.transition_status(JobAction.DEFER, message="failure", bogus=True)
