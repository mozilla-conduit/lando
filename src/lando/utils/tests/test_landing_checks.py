import io
from unittest.mock import patch

import pytest
import requests
import rs_parsepatch

from lando.main.scm.helpers import (
    GitPatchHelper,
    HgPatchHelper,
)
from lando.utils.landing_checks import (
    ALL_CHECKS,
    BugReferencesCheck,
    CommitMessagesCheck,
    LandingChecks,
    PatchCollectionAssessor,
    PreventNSPRNSSCheck,
    PreventSubmodulesCheck,
    TryTaskConfigCheck,
    WPTSyncCheck,
)

GIT_DIFF_FILENAME_TEMPLATE = r"""\
diff --git a/{filename} b/{filename}
--- a/{filename}
+++ b/{filename}
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {{
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }}
"""


GIT_PATCH_FILENAME_TEMPLATE = (
    r"""
From 0f5a3c99e12c1e9b0e81bed245fe537961f89e57 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: Change things
---
 {filename} | 8 +++++++-
 1 file changed, 7 insertions(+), 1 deletion(-)

""".lstrip()
    + GIT_DIFF_FILENAME_TEMPLATE
)

COMMIT_MESSAGE = """A commit message to check

Let's make sure everything checks out.
"""


def test_check_commit_message_merge_automation_empty_message():
    patch_helpers = [
        HgPatchHelper.from_string_io(
            io.StringIO(
                """
# HG changeset patch
# User ffxbld
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]

    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    # Test check fails for empty commit message.
    assert assessor.run_patch_collection_checks(
        patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
    ) == [
        "Revision has an empty commit message."
    ], "Commit message check should fail if a commit message is passed but it is empty."


def test_check_commit_message_merge_automation_bad_message():
    patch_helpers = [
        HgPatchHelper.from_string_io(
            io.StringIO(
                """
# HG changeset patch
# User ffxbld
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
this message is missing the bug.

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]

    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    # Test check passed for merge automation user.
    assert (
        assessor.run_patch_collection_checks(
            patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
        )
        == []
    ), "Commit message check should pass if a merge automation user is the author."


@pytest.mark.parametrize(
    "commit_message,error_message",
    [
        (
            "Bug 123: this message has a bug number",
            "Bug XYZ syntax is accepted.",
        ),
        (
            "No bug: this message has a bug number",
            "'No bug' syntax is accepted.",
        ),
        (
            "Backed out changeset 4910f543acd8",
            "'Backed out' backout syntax is accepted.",
        ),
        (
            "Backout of ceac31c0ce89 due to bustage",
            "'Backout of' backout syntax is accepted.",
        ),
        (
            "Revert to changeset 41f80b316d60 due to incomplete backout",
            "'Revert to' backout syntax is accepted.",
        ),
        (
            "Backout changesets  9e4ab3907b29, 3abc0dbbf710 due to m-oth permaorange",
            "Multiple changesets are allowed for backout syntax.",
        ),
        (
            "Added tag AURORA_BASE_20110412 for changeset 2d4e565cf83f",
            "Tag syntax should be allowed.",
        ),
    ],
)
def test_check_commit_message_valid_message(commit_message: str, error_message: str):
    patch_helpers = [
        HgPatchHelper.from_string_io(
            io.StringIO(
                f"""
# HG changeset patch
# User Connor Sheehan <sheehan@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
{commit_message}

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]
    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    assert (
        assessor.run_patch_collection_checks(
            patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
        )
        == []
    ), error_message


@pytest.mark.parametrize(
    "commit_message,return_string,error_message",
    [
        (
            "this message is missing the bug.",
            "Revision needs 'Bug N' or 'No bug' in the commit message: ",
            "Commit message is rejected without a bug number.",
        ),
        (
            "Mass revert m-i to the last known good state",
            "Revision needs 'Bug N' or 'No bug' in the commit message: ",
            "Revision missing a bug number or no bug should result in a failed check.",
        ),
        (
            "update revision of Add-on SDK tests to latest tip; test-only",
            "Revision needs 'Bug N' or 'No bug' in the commit message: ",
            "Revision missing a bug number or no bug should result in a failed check.",
        ),
        (
            "Fix stupid bug in foo::bar()",
            "Revision needs 'Bug N' or 'No bug' in the commit message: ",
            "Commit message with 'bug' bug in improper format should result in a failed check.",
        ),
        (
            "Back out Dao's push because of build bustage",
            "Revision is a backout but commit message does not indicate backed out revisions: ",
            "Backout should be rejected when a reference to the original patch is missing.",
        ),
        (
            "Bug 100 - Foo. r?bar",
            "Revision contains 'r?' in the commit message. Please use 'r=' instead: ",
            "Improper review specifier should be rejected.",
        ),
        (
            "WIP: bug 123: this is a wip r=reviewer",
            "Revision seems to be marked as WIP: ",
            "WIP revisions should be rejected.",
        ),
        (
            "[PATCH 1/2] first part of my git patch",
            (
                "Revision contains git-format-patch '[PATCH]' cruft. "
                "Use git-format-patch -k to avoid this: "
            ),
            "`git-format-patch` cruft should result in a failed check.",
        ),
    ],
)
def test_check_commit_message_invalid_message(
    commit_message: str, return_string: str, error_message: str
):
    patch_helpers = [
        HgPatchHelper.from_string_io(
            io.StringIO(
                f"""
# HG changeset patch
# User Connor Sheehan <sheehan@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
{commit_message}

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]
    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    assert assessor.run_patch_collection_checks(
        patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
    ) == [return_string + commit_message], error_message


@pytest.mark.parametrize(
    "push_user_email,patch,return_string,error_message",
    [
        (
            "sheehan@mozilla.com",
            GIT_PATCH_FILENAME_TEMPLATE.format(filename="somefile.txt"),
            None,
            "Non-WPT pushes by non-WPT user should be allowed",
        ),
        (
            "wptsync@mozilla.com",
            GIT_PATCH_FILENAME_TEMPLATE.format(filename="somefile.txt"),
            "Revision has WPTSync bot making changes to disallowed "
            + "files `somefile.txt`.",
            "Non-WPT pushes by WPT user should not be allowed",
        ),
        (
            "wptsync@mozilla.com",
            GIT_PATCH_FILENAME_TEMPLATE.format(
                filename="testing/web-platform/moz.build"
            ),
            None,
            "WPT pushes by non-WPT user should be allowed",
        ),
    ],
)
def test_check_wptsync_git(
    push_user_email: str, patch: str, return_string: str | None, error_message: str
):
    patch_helpers = [GitPatchHelper.from_string_io(io.StringIO(patch))]
    assessor = PatchCollectionAssessor(
        patch_helpers=patch_helpers, push_user_email=push_user_email
    )

    errors = assessor.run_patch_collection_checks(
        patch_collection_checks=[WPTSyncCheck], patch_checks=[]
    )

    if return_string:
        assert errors == [return_string], error_message
    else:
        assert not errors, error_message


def test_check_prevent_nspr_nss_missing_fields():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Missing commit message should result in passing check."


def test_check_prevent_nspr_nss_nss():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: vendored NSS directories: "
        "`security/nss/testfile.txt`."
    ), "Check should disallow changes to NSS without proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Check should allow changes to NSS with proper commit message."


def test_check_prevent_nspr_nss_nspr():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt")
    )
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: vendored NSPR directories: "
        "`nsprpub/testfile.txt`."
    ), "Check should disallow changes to NSPR without proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSPR_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Check should allow changes to NSPR with proper commit message."


def test_check_prevent_nspr_nss_combined():
    nspr_patch = GIT_DIFF_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt")
    nss_patch = GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    combined_patch = "\n".join((nspr_patch, nss_patch))

    parsed_diff = rs_parsepatch.get_diffs(combined_patch)
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: vendored NSS directories: "
        "`security/nss/testfile.txt` vendored NSPR directories: `nsprpub/testfile.txt`."
    ), "Check should disallow changes to both NSS and NSPR without proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSPR_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: "
        "vendored NSS directories: `security/nss/testfile.txt`."
    ), "Check should allow changes to NSPR with proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: "
        "vendored NSPR directories: `nsprpub/testfile.txt`."
    ), "Check should allow changes to NSPR with proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE UPGRADE_NSPR_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Check should allow changes to NSPR with proper commit message."


def test_check_prevent_submodules():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    prevent_submodules_check = PreventSubmodulesCheck()
    for diff in parsed_diff:
        prevent_submodules_check.next_diff(diff)

    assert (
        prevent_submodules_check.result() is None
    ), "Check should pass when no submodules are introduced."

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename=".gitmodules")
    )
    prevent_submodules_check = PreventSubmodulesCheck()
    for diff in parsed_diff:
        prevent_submodules_check.next_diff(diff)

    assert (
        prevent_submodules_check.result()
        == "Revision introduces a Git submodule into the repository."
    ), "Check should prevent revisions from introducing submodules."


def test_check_bug_references_public_bugs():
    patch_helper = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
bug 123: WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate contacting BMO returning a public bug state.
    with (
        patch("lando.utils.landing_checks.get_status_code_for_bug") as mock_status_code,
        patch("lando.utils.landing_checks.search_bugs") as mock_bug_search,
    ):
        mock_bug_search.side_effect = lambda bug_ids: bug_ids

        # Mock out the status code check to simulate a public bug.
        mock_status_code.return_value = 200

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

        assert (
            assessor.run_patch_collection_checks(
                patch_collection_checks=[BugReferencesCheck],
                patch_checks=[],
            )
            == []
        )


def test_check_bug_references_private_bugs():
    # Simulate a patch that references a private bug.
    patch_helper = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
Bug 999999: Fix issue with feature X
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate Bugzilla (BMO) responding that the bug is private.
    with (
        patch("lando.utils.landing_checks.get_status_code_for_bug") as mock_status_code,
        patch("lando.utils.landing_checks.search_bugs") as mock_bug_search,
    ):
        # Mock out bug search to simulate our bug not being found.
        mock_bug_search.return_value = set()

        # Mock out the status code check to simulate a private bug.
        mock_status_code.return_value = 401

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)
        issues = assessor.run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[],
        )

        assert (
            "Your commit message references bug 999999, which is currently private."
            in issues[0]
        )


def test_check_bug_references_skip_check():
    # Simulate a patch with SKIP_BMO_CHECK in the commit message.
    patch_helper = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
Bug 999999: Fix issue with feature X
SKIP_BMO_CHECK
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate Bugzilla (BMO) responding that the bug is private.
    with (
        patch("lando.utils.landing_checks.get_status_code_for_bug") as mock_status_code,
        patch("lando.utils.landing_checks.search_bugs") as mock_bug_search,
    ):
        # Mock out bug search to simulate our bug not being found.
        mock_bug_search.return_value = set()

        # Mock out the status code check to simulate a private bug.
        mock_status_code.return_value = 401

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)
        issues = assessor.run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[],
        )

        assert (
            issues == []
        ), "Check should always pass when `SKIP_BMO_CHECK` is present."


def test_check_bug_references_bmo_error():
    # Simulate a patch that references a bug.
    patch_helper = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
Bug 123456: Fix issue with feature Y
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate an error occurring when trying to contact BMO.
    with (
        patch("lando.utils.landing_checks.get_status_code_for_bug") as mock_status_code,
        patch("lando.utils.landing_checks.search_bugs") as mock_bug_search,
    ):
        mock_bug_search.return_value = set()

        def status_error(*args, **kwargs):
            raise requests.exceptions.RequestException("BMO connection failed")

        mock_status_code.side_effect = status_error

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)
        issues = assessor.run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[],
        )

        assert (
            issues
            and "Could not contact BMO to check for security bugs referenced in commit message."
            in issues[0]
        )


def test_check_try_task_config():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    try_task_config_check = TryTaskConfigCheck()
    for diff in parsed_diff:
        try_task_config_check.next_diff(diff)

    assert (
        try_task_config_check.result() is None
    ), "Check should pass when no try_task_config.json is introduced."

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="try_task_config.json")
    )
    try_task_config_check = TryTaskConfigCheck()
    for diff in parsed_diff:
        try_task_config_check.next_diff(diff)

    assert (
        try_task_config_check.result()
        == "Revision introduces the `try_task_config.json` file."
    ), "Check should prevent revisions from adding try_task_config.json."


def test_landing_checks_run():
    landing_checks = LandingChecks("user@example.com")

    # CommitMessagesCheck will get triggered as neither commits conform.
    patch_helpers = [
        GitPatchHelper.from_string_io(
            io.StringIO(
                # TryTaskConfigCheck will get triggered.
                GIT_PATCH_FILENAME_TEMPLATE.format(filename="try_task_config.json"),
            )
        ),
        GitPatchHelper.from_string_io(
            io.StringIO(
                # PreventNSPRNSSCheck will get triggered.
                GIT_PATCH_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt"),
            )
        ),
    ]

    names_run = landing_checks.run([chk.name() for chk in ALL_CHECKS], patch_helpers)

    assert len(names_run) == 3
    assert all_checks_run == names_run
