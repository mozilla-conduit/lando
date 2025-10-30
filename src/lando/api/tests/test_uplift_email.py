from lando.api.legacy.email import (
    make_uplift_failure_email,
    make_uplift_success_email,
)

FAILURE_EXPECTED_BODY = """
Your uplift request for firefox-beta did not complete successfully.

See here for details and merge conflicts: https://lando/jobs/1

Reason:
moz-phab uplift exited with code 2

Review the job details linked above for more information, including
details of any merge conflicts that were encountered.

If your uplift failed due to merge conflicts, this means your patch
cannot be uplifted without manually resolving the merge conflicts and
re-submitting. Please pull the latest changes for firefox-beta, resolve
the conflicts locally, and submit a new uplift request using `moz-phab
uplift` once the conflicts are cleared.

See https://wiki.mozilla.org/index.php?title=Release_Management/Requesting_an_Uplift
for step-by-step instructions.
""".strip()


def test_make_uplift_failure_email():
    email = make_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/1",
        "moz-phab uplift exited with code 2",
    )

    assert email.subject == "Lando: Uplift for firefox-beta failed"
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
