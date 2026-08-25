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

MAX_ATTEMPTS = 3


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


@pytest.mark.parametrize(
    "attempts,remaining",
    (
        (0, True),
        (MAX_ATTEMPTS - 1, True),
        (MAX_ATTEMPTS, False),
        (MAX_ATTEMPTS + 1, False),
    ),
)
def test__models__BaseJob__has_attempts_remaining(
    monkeypatch: pytest.MonkeyPatch, attempts: int, remaining: bool
):
    # `max_attempts` reads a configuration variable, which would need the database.
    monkeypatch.setattr(LandingJob, "max_attempts", MAX_ATTEMPTS)
    job = LandingJob(status=JobStatus.SUBMITTED, attempts=attempts)

    assert job.has_attempts_remaining() is remaining, (
        f"A job with {attempts} of {MAX_ATTEMPTS} attempts should have "
        f"{'attempts' if remaining else 'no attempts'} remaining."
    )


@pytest.mark.django_db
def test__models__BaseJob__abort_sets_templated_error(make_landing_job: Callable):
    job = make_landing_job(status=JobStatus.IN_PROGRESS, attempts=3)

    job.transition_status(JobAction.ABORT, message="the last failure")

    assert job.status == JobStatus.ABORTED, "`ABORT` should abort the job."
    assert job.error == ABORTED_ERROR_TEMPLATE.format(
        attempts=3, message="the last failure"
    ), "The error should explain the abort and quote the last failure verbatim."


@pytest.mark.django_db
def test__models__BaseJob__max_attempts_configuration(make_landing_job: Callable):
    job = make_landing_job(status=JobStatus.SUBMITTED)

    assert job.max_attempts == DEFAULT_MAX_JOB_ATTEMPTS, (
        "The default should be used while `MAX_JOB_ATTEMPTS` is unset."
    )

    ConfigurationVariable.set(
        ConfigurationKey.MAX_JOB_ATTEMPTS, VariableTypeChoices.INT, "2"
    )

    assert job.max_attempts == 2, (
        "`MAX_JOB_ATTEMPTS` should be used instead of the default."
    )
