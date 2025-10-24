import pytest

from lando.api.legacy.email import (
    build_uplift_conflict_summary,
    make_uplift_failure_email,
    make_uplift_success_email,
)


@pytest.mark.parametrize(
    "conflicts, expected",
    [
        (
            [
                {"path": "path/to/file.txt", "snippet": "<<<<<<< ours\n..."},
                {"path": "second.txt", "snippet": ""},
            ],
            "- path/to/file.txt\n<<<<<<< ours\n...\n\n- second.txt\n(No conflict markers were captured.)",
        ),
        (
            [],
            "",
        ),
    ],
)
def test_build_uplift_conflict_summary(conflicts, expected):
    assert build_uplift_conflict_summary(conflicts) == expected


FAILURE_WITHOUT_CONFLICTS_EXPECTED_BODY = """
Your uplift request for firefox-beta did not complete successfully.

Job details: https://lando/jobs/1

Reason:
moz-phab uplift exited with code 2

Review the job details linked above, address the failure in
your patch stack, and resubmit the uplift request when ready.
""".strip()


def test_make_uplift_failure_email_without_conflicts():
    email = make_uplift_failure_email(
        "user@example.com",
        "firefox-beta",
        "https://lando/jobs/1",
        "moz-phab uplift exited with code 2",
        conflict_sections=None,
    )

    assert email.subject == "Lando: Uplift for firefox-beta failed"
    assert email.body == FAILURE_WITHOUT_CONFLICTS_EXPECTED_BODY


FAILURE_WITH_CONFLICTS_EXPECTED_BODY = """
Your uplift request for firefox-release did not complete successfully.

Job details: https://lando/jobs/99

Reason:
Patch conflicts

Lando detected merge conflicts while applying your stack. This
means your patch cannot be uplifted without manually resolving
the merge conflicts and re-submitting. Please pull the latest
changes for firefox-release, resolve the conflicts locally,
and submit a new uplift request using `moz-phab uplift`
once the conflicts are cleared.

See https://wiki.mozilla.org/index.php?title=Release_Management/Requesting_an_Uplift
for step-by-step instructions.

Conflict markers were reported in:
- browser/app.cpp
<<<<<<< ours
foo
=======
bar
""".strip()


def test_make_uplift_failure_email_with_conflicts():
    conflict_sections = [
        {"path": "browser/app.cpp", "snippet": "<<<<<<< ours\nfoo\n=======\nbar"},
    ]

    email = make_uplift_failure_email(
        "user@example.com",
        "firefox-release",
        "https://lando/jobs/99",
        "Patch conflicts",
        conflict_sections=conflict_sections,
    )

    assert email.subject == "Lando: Uplift for firefox-release failed"
    assert email.body == FAILURE_WITH_CONFLICTS_EXPECTED_BODY


SUCCESS_EXPECTED_BODY = """
Your uplift request for firefox-esr finished successfully.

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
        ["D1234", "D5678"],
    )

    assert email.subject == "Lando: Uplift for firefox-esr succeeded"
    assert email.body == SUCCESS_EXPECTED_BODY
