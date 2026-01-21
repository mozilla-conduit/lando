from lando.api.legacy.email import (
    make_uplift_failure_email,
    make_uplift_success_email,
)
from lando.utils.const import UPLIFT_DOCS_URL

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

Once you have created a new uplift Phabricator revision, you can use the
"Reuse Previous Assessment" button to reuse your previously submitted
uplift assessment form with the new revision.

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
