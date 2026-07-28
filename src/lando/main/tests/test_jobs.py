from typing import Callable

import pytest

from lando.headless_api.models.automation_job import AutomationJob
from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
from lando.main.models.jobs import (
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


def attempt_and_defer(job: LandingJob, times: int, abortable: bool = True):
    """Attempt and defer `job` `times` times, as the worker would."""
    for attempt in range(times):
        job.start_attempt()
        job.transition_status(
            JobAction.DEFER, message=f"failure {attempt}", abortable=abortable
        )


@pytest.mark.django_db
def test__models__BaseJob__job_aborted_after_max_attempts(make_landing_job: Callable):
    job = make_landing_job(status=JobStatus.SUBMITTED)

    attempt_and_defer(job, DEFAULT_MAX_JOB_ATTEMPTS - 1)
    assert job.status == JobStatus.DEFERRED, (
        "Job should still be deferred below the maximum number of attempts."
    )

    attempt_and_defer(job, 1)
    assert job.status == JobStatus.ABORTED, (
        "Job should be aborted once it reaches the maximum number of attempts."
    )
    assert "Lando gave up on this job" in job.error, (
        "Error message should explain that the job was aborted."
    )
    assert "failure 0" in job.error, (
        "Error message should include the reason for the last failure."
    )


@pytest.mark.django_db
def test__models__BaseJob__non_abortable_deferrals_do_not_abort_job(
    make_landing_job: Callable,
):
    job = make_landing_job(status=JobStatus.SUBMITTED)

    attempt_and_defer(job, DEFAULT_MAX_JOB_ATTEMPTS * 2, abortable=False)

    assert job.status == JobStatus.DEFERRED, (
        "Non-abortable deferrals should never abort the job."
    )
    assert job.attempts == 0, "Non-abortable deferrals should give their attempt back."


@pytest.mark.django_db
def test__models__BaseJob__attempt_only_handled_once(make_landing_job: Callable):
    """A single attempt may defer through more than one code path."""
    job = make_landing_job(status=JobStatus.IN_PROGRESS, attempts=1)

    job.transition_status(JobAction.DEFER, message="failure", abortable=False)
    job.transition_status(JobAction.DEFER, message="failure", abortable=False)

    assert job.attempts == 0, (
        "Re-deferring an already deferred job should not give another attempt back."
    )


@pytest.mark.parametrize(
    "variable_type,raw_value,expected",
    (
        (VariableTypeChoices.INT, "2", 2),
        # `VariableTypeChoices.STR` is the default type, so it is easy to save
        # `MAX_JOB_ATTEMPTS` without converting it to an integer.
        (VariableTypeChoices.STR, "2", 2),
        (VariableTypeChoices.STR, "ten", DEFAULT_MAX_JOB_ATTEMPTS),
        (VariableTypeChoices.INT, "ten", DEFAULT_MAX_JOB_ATTEMPTS),
        (VariableTypeChoices.INT, "0", DEFAULT_MAX_JOB_ATTEMPTS),
        (VariableTypeChoices.INT, "-1", DEFAULT_MAX_JOB_ATTEMPTS),
    ),
)
@pytest.mark.django_db
def test__models__BaseJob__max_attempts_configuration(
    make_landing_job: Callable,
    variable_type: VariableTypeChoices,
    raw_value: str,
    expected: int,
):
    # Create the row directly, since `ConfigurationVariable.set` refuses some of
    # these values while the Django admin does not.
    ConfigurationVariable.objects.create(
        key=ConfigurationKey.MAX_JOB_ATTEMPTS.value,
        variable_type=variable_type,
        raw_value=raw_value,
    )
    job = make_landing_job(status=JobStatus.SUBMITTED)

    assert job.max_attempts == expected, (
        f"`MAX_JOB_ATTEMPTS` of {raw_value!r} as {variable_type} "
        f"should resolve to {expected}."
    )

    attempt_and_defer(job, expected - 1)

    assert job.status == JobStatus.DEFERRED, (
        "The job should not be aborted before its last allowed attempt."
    )

    attempt_and_defer(job, 1)

    assert job.status == JobStatus.ABORTED, (
        "The job should be aborted on its last allowed attempt."
    )


@pytest.mark.django_db
def test__models__BaseJob__transition_status_rejects_unknown_params(
    make_landing_job: Callable,
):
    job = make_landing_job(status=JobStatus.SUBMITTED)

    with pytest.raises(ValueError):
        job.transition_status(JobAction.DEFER, message="failure", bogus=True)
