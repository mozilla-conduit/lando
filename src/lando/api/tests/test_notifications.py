import inspect

import pytest
from django.core import mail

from lando.api.legacy.email import make_failure_email
from lando.api.legacy.notifications import notify_user_of_landing_failure
from lando.main.models.landing_job import LandingJob
from lando.main.models.revision import Revision
from lando.utils.tasks import send_landing_failure_email

dedent = inspect.cleandoc


def test_send_failure_notification_email_task(app):  # noqa: ANN001
    send_landing_failure_email("sadpanda@failure.test", "D54321", "Rebase failed!")
    assert len(mail.outbox) == 1


def test_email_content_phabricator():
    email = make_failure_email(
        "sadpanda@failure.test",
        "D54321",
        "Rebase failed!",
    )
    assert email.to == ["sadpanda@failure.test"]
    assert email.subject == "Lando: Landing of D54321 failed!"
    expected_body = (
        "Your request to land D54321 failed.\n\n"
        "See https://lando.test/D54321/ for details.\n\n"
        "Reason:\n"
        "Rebase failed!"
    )
    assert email.body == expected_body


def test_email_content_try():
    email = make_failure_email(
        "sadpanda@failure.test",
        "try push with tip commit 'testing 123'",
        "Rebase failed!",
    )
    assert email.to == ["sadpanda@failure.test"]
    assert (
        email.subject
        == "Lando: Landing of try push with tip commit 'testing 123' failed!"
    )
    expected_body = (
        "Your request to land try push with tip commit 'testing 123' failed.\n\n"
        "Reason:\n"
        "Rebase failed!"
    )
    assert email.body == expected_body


@pytest.mark.django_db(transaction=True)
def test_notify_user_of_landing_failure(app):  # noqa: ANN001
    # Testing happy path only (as part of porting this test).
    # TODO: should test actual functionality more broadly.
    job = LandingJob(revision_order=["1"])
    job.save()
    revision = Revision(patch_data={})
    revision.save()
    job.unsorted_revisions.add(revision)
    notify_user_of_landing_failure(
        job.requester_email,
        job.landing_job_identifier,
        job.error,
        job.id,
    )
