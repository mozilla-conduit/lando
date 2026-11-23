import pytest

from lando.api.legacy.email import (
    make_pull_request_uplift_failure_email,
    make_pull_request_uplift_success_email,
    make_uplift_failure_email,
    make_uplift_success_email,
)
from lando.utils.const import UPLIFT_DOCS_URL
from lando.utils.tasks import send_uplift_failure_email, send_uplift_success_email

FAILURE_EXPECTED_BODY = f"""
Your uplift request for firefox-beta did not complete successfully.

WHAT TO DO NEXT:

Visit your original revision page to see clear resolution instructions:
https://lando.test/D456/

On this page, click the "Show resolution steps" button to see the exact
commands you need to run to resolve merge conflicts and submit your uplift.

HOW TO RESOLVE:

Most uplift failures are due to merge conflicts. To resolve:
1. Pull the latest changes for firefox-beta
2. Resolve any merge conflicts locally
3. Submit a new uplift request using `moz-phab uplift`

Once you have created a new uplift Phabricator revision, open its Lando
page and pick your previously submitted uplift assessment in the
checklist under "Uplifts" to reuse it with the new revision.

For detailed step-by-step instructions, see {UPLIFT_DOCS_URL}

TECHNICAL DETAILS:

Job details: https://lando/jobs/1

Reason for failure:
moz-phab uplift exited with code 2
""".strip()


def test_make_uplift_failure_email():
    email = make_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/1",
        "moz-phab uplift exited with code 2",
        [123, 456],
    )

    assert email.subject == "Lando: Uplift for firefox-beta failed (D456)"
    assert email.body == FAILURE_EXPECTED_BODY


SUCCESS_EXPECTED_BODY = """
Your uplift request for firefox-esr finished successfully.

Requested revisions:
- D123
- D456

Lando created the following revisions:
- D1234
- D5678

You can review the full job details at https://lando/jobs/123.

Thank you for keeping the uplift train moving!
""".strip()


def test_make_uplift_success_email():
    email = make_uplift_success_email(
        "user@example.com",
        "firefox-esr",
        "https://lando/jobs/123",
        [1234, 5678],
        [123, 456],
    )

    assert email.subject == "Lando: Uplift for firefox-esr succeeded (D456)"
    assert email.body == SUCCESS_EXPECTED_BODY


PULL_REQUEST_FAILURE_EXPECTED_BODY = f"""
Your uplift request for firefox-beta did not complete successfully.

WHAT TO DO NEXT:

Visit your pull request page (PR #342) to see clear resolution instructions:
https://lando.test/pulls/firefox-autoland/342/

Under "Uplifts", click the "Show resolution steps" button to see the exact
commands you need to run to resolve merge conflicts and submit your uplift.

HOW TO RESOLVE:

Most uplift failures are due to merge conflicts. To resolve:
1. Pull the latest changes for firefox-beta
2. Apply the commits from your pull request and resolve any merge conflicts locally
3. Submit a new uplift request using `moz-phab uplift`

Once you have created a new uplift Phabricator revision, open its Lando
page and pick your previously submitted uplift assessment in the
checklist under "Uplifts" to reuse it with the new revision.

For detailed step-by-step instructions, see {UPLIFT_DOCS_URL}

TECHNICAL DETAILS:

Job details: https://lando/jobs/1

Reason for failure:
moz-phab uplift exited with code 2
""".strip()


def test_make_pull_request_uplift_failure_email():
    email = make_pull_request_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/1",
        "moz-phab uplift exited with code 2",
        "https://lando.test/pulls/firefox-autoland/342/",
        342,
    )

    assert email.subject == "Lando: Uplift for firefox-beta failed (PR #342)", (
        "The subject should name the pull request being uplifted."
    )
    assert email.body == PULL_REQUEST_FAILURE_EXPECTED_BODY, (
        "The body should use the pull request failure template."
    )
    assert email.to == ["user@example.com"], (
        "The email should be sent to the requester."
    )


PULL_REQUEST_SUCCESS_EXPECTED_BODY = """
Your uplift request for firefox-beta finished successfully.

Requested pull request:
- PR #342: https://lando.test/pulls/firefox-autoland/342/

Lando created the following Phabricator revisions:
- D1234
- D1235

You can review the full job details at https://lando/jobs/123.

Thank you for keeping the uplift train moving!
""".strip()


def test_make_pull_request_uplift_success_email():
    email = make_pull_request_uplift_success_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/123",
        [1234, 1235],
        "https://lando.test/pulls/firefox-autoland/342/",
        342,
    )

    assert email.subject == "Lando: Uplift for firefox-beta succeeded (PR #342)", (
        "The subject should name the pull request being uplifted."
    )
    assert email.body == PULL_REQUEST_SUCCESS_EXPECTED_BODY, (
        "The body should use the pull request success template."
    )
    assert email.to == ["user@example.com"], (
        "The email should be sent to the requester."
    )


@pytest.mark.parametrize(
    "pull_request_url, pull_request_number, expected_subject",
    [
        (
            "https://lando.test/pulls/firefox-autoland/342/",
            342,
            "Lando: Uplift for firefox-beta succeeded (PR #342)",
        ),
        (None, None, "Lando: Uplift for firefox-beta succeeded (D456)"),
    ],
)
def test_send_uplift_success_email_picks_template(
    mailoutbox, pull_request_url, pull_request_number, expected_subject
):
    send_uplift_success_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/123",
        [1234],
        [456],
        pull_request_url,
        pull_request_number,
    )

    assert len(mailoutbox) == 1, "`send_uplift_success_email` should send one email."
    assert mailoutbox[0].subject == expected_subject, (
        "The task should use the pull request template only for pull request uplifts."
    )


@pytest.mark.parametrize(
    "pull_request_url, pull_request_number, expected_subject",
    [
        (
            "https://lando.test/pulls/firefox-autoland/342/",
            342,
            "Lando: Uplift for firefox-beta failed (PR #342)",
        ),
        (None, None, "Lando: Uplift for firefox-beta failed (D456)"),
    ],
)
def test_send_uplift_failure_email_picks_template(
    mailoutbox, pull_request_url, pull_request_number, expected_subject
):
    send_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/1",
        "moz-phab uplift exited with code 2",
        [456],
        pull_request_url,
        pull_request_number,
    )

    assert len(mailoutbox) == 1, "`send_uplift_failure_email` should send one email."
    assert mailoutbox[0].subject == expected_subject, (
        "The task should use the pull request template only for pull request uplifts."
    )
