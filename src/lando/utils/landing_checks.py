from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

import requests
import rs_parsepatch

from lando.api.legacy.bmo import (
    get_status_code_for_bug,
    search_bugs,
)
from lando.api.legacy.commit_message import (
    ACCEPTABLE_MESSAGE_FORMAT_RES,
    INVALID_REVIEW_FLAG_RE,
    is_backout,
    parse_backouts,
    parse_bugs,
)
from lando.main.scm.helpers import PatchHelper

# Decimal notation for the `symlink` file mode.
SYMLINK_MODE = 40960

# WPTSync bot is restricted to paths matching this regex.
WPTSYNC_ALLOWED_PATHS_RE = re.compile(
    r"testing/web-platform/(?:moz\.build|meta/.*|tests/.*)$"
)


def wrap_filenames(filenames: list[str]) -> str:
    """Convert a list of filenames to a string with names wrapped in backticks."""
    return ",".join(f"`{filename}`" for filename in filenames)


@dataclass
class Check(ABC):
    """A base class for check, providing human-friendly identification attributes."""

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """Human-friendly name for this check."""

    @classmethod
    @abstractmethod
    def description(cls) -> str:
        """Human-friendly description for this check."""


@dataclass
class PatchCheck(Check, ABC):
    """Provides an interface to implement patch checks.

    When looping over each diff in the patch, `next_diff` is called to give the
    current diff to the patch as a `rs_parsepatch` diff `dict`. Then, `result` is
    called to receive the result of the check.
    """

    author: str | None = None
    email: str | None = None
    commit_message: str | None = None

    @abstractmethod
    def next_diff(self, diff: dict):
        """Pass the next `rs_parsepatch` diff `dict` into the check."""

    @abstractmethod
    def result(self) -> str | None:
        """Calculate and return the result of the check."""


@dataclass
class PreventSymlinksCheck(PatchCheck):
    """Check for symlinks introduced in the diff."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PreventSymlinksCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "Check for symlinks introduced in the diff."

    symlinked_files: list[str] = field(default_factory=list)

    def next_diff(self, diff: dict):
        modes = diff["modes"]

        # Check the file mode on each file and ensure the file is not a symlink.
        # `rs_parsepatch` has a `new` and `old` mode key, we are interested in
        # only the newly introduced modes.
        if "new" in modes and modes["new"] == SYMLINK_MODE:
            self.symlinked_files.append(diff["filename"])

    def result(self) -> str | None:
        if self.symlinked_files:
            return (
                "Revision introduces symlinks in the files "
                f"{wrap_filenames(self.symlinked_files)}."
            )


@dataclass
class TryTaskConfigCheck(PatchCheck):
    """Check for `try_task_config.json` introduced in the diff."""

    @override
    @classmethod
    def name(cls) -> str:
        return "TryTaskConfigCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "Check for `try_task_config.json` introduced in the diff."

    includes_try_task_config: bool = False

    def next_diff(self, diff: dict):
        """Check each diff for the `try_task_config.json` file."""
        if diff["filename"] == "try_task_config.json":
            self.includes_try_task_config = True

    def result(self) -> str | None:
        """Return an error if the `try_task_config.json` was found."""
        if self.includes_try_task_config:
            return "Revision introduces the `try_task_config.json` file."


@dataclass
class PreventNSPRNSSCheck(PatchCheck):
    """Prevent changes to vendored NSPR directories."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PreventNSPRNSSCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "Prevent changes to vendored NSPR directories."

    nss_disallowed_changes: list[str] = field(default_factory=list)
    nspr_disallowed_changes: list[str] = field(default_factory=list)

    def build_prevent_nspr_nss_error_message(self) -> str:
        """Build the `check_prevent_nspr_nss` error message.

        Assumes at least one of `nss_disallowed_changes` or `nspr_disallowed_changes`
        are non-empty lists.
        """
        # Build the error message.
        return_error_message = ["Revision makes changes to restricted directories:"]

        if self.nss_disallowed_changes:
            return_error_message.append("vendored NSS directories:")

            return_error_message.append(wrap_filenames(self.nss_disallowed_changes))

        if self.nspr_disallowed_changes:
            return_error_message.append("vendored NSPR directories:")

            return_error_message.append(wrap_filenames(self.nspr_disallowed_changes))

        return f"{' '.join(return_error_message)}."

    def next_diff(self, diff: dict):
        """Pass the next `rs_parsepatch` diff `dict` into the check."""
        if not self.commit_message:
            return

        filename = diff["filename"]

        if (
            filename.startswith("security/nss/")
            and "UPGRADE_NSS_RELEASE" not in self.commit_message
        ):
            self.nss_disallowed_changes.append(filename)

        if (
            filename.startswith("nsprpub/")
            and "UPGRADE_NSPR_RELEASE" not in self.commit_message
        ):
            self.nspr_disallowed_changes.append(filename)

    def result(self) -> str | None:
        """Calculate and return the result of the check."""
        if not self.nss_disallowed_changes and not self.nspr_disallowed_changes:
            # Return early if no disallowed changes were found.
            return

        return self.build_prevent_nspr_nss_error_message()


@dataclass
class PreventSubmodulesCheck(PatchCheck):
    """Prevent introduction of Git submodules into the repository."""

    @override
    @classmethod
    def name(cls) -> str:
        return "PreventSubmodulesCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "Prevent introduction of Git submodules into the repository."

    includes_gitmodules: bool = False

    def next_diff(self, diff: dict):
        """Check if a diff adds the `.gitmodules` file."""
        if diff["filename"] == ".gitmodules":
            self.includes_gitmodules = True

    def result(self) -> str | None:
        """Return an error if the `.gitmodules` file was found."""
        if self.includes_gitmodules:
            return "Revision introduces a Git submodule into the repository."


@dataclass
class DiffAssessor:
    """Assess diffs for landing issues.

    Diffs should be passed in `rs-parsepatch` format.
    """

    parsed_diff: list[dict]
    author: str | None = None
    email: str | None = None
    commit_message: str | None = None

    def run_diff_checks(self, patch_checks: list[type[PatchCheck]]) -> list[str]:
        """Execute the set of checks on the diffs."""
        issues = []

        checks = [
            check(
                author=self.author,
                commit_message=self.commit_message,
                email=self.email,
            )
            for check in patch_checks
        ]

        # Iterate through each diff in the patch and pass it into each check.
        for parsed in self.parsed_diff:
            for check in checks:
                check.next_diff(parsed)

        # Collect the results from each check.
        for check in checks:
            if issue := check.result():
                issues.append(issue)

        return issues


@dataclass
class PatchCollectionCheck(Check, ABC):
    """Provides an interface to implement patch collection checks.

    When looping over each patch in the collection, `next_diff` is called to give the
    current diff to the patch as a `PatchHelper` subclass. Then, `result` is
    called to receive the result of the check.
    """

    push_user_email: str | None = None

    @abstractmethod
    def next_diff(self, patch_helper: PatchHelper):
        """Pass the next `PatchHelper` into the check."""

    @abstractmethod
    def result(self) -> str | None:
        """Calculate and return the result of the check."""


@dataclass
class CommitMessagesCheck(PatchCollectionCheck):
    """Check the format of the passed commit message for issues."""

    @override
    @classmethod
    def name(cls) -> str:
        return "CommitMessagesCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "Check the format of the passed commit message for issues."

    ignore_bad_commit_message: bool = False
    commit_message_issues: list[str] = field(default_factory=list)

    def next_diff(self, patch_helper: PatchHelper):
        """Pass the next `rs_parsepatch` diff `dict` into the check."""
        commit_message = patch_helper.get_commit_description()
        author, _email = patch_helper.parse_author_information()

        if not commit_message:
            self.commit_message_issues.append("Revision has an empty commit message.")
            return

        firstline = commit_message.splitlines()[0]

        if self.ignore_bad_commit_message or "IGNORE BAD COMMIT MESSAGES" in firstline:
            self.ignore_bad_commit_message = True
            return

        # Ensure backout commit descriptions are well formed.
        if is_backout(firstline):
            backouts = parse_backouts(firstline, strict=True)
            if not backouts or not backouts[0]:
                self.commit_message_issues.append(
                    "Revision is a backout but commit message "
                    f"does not indicate backed out revisions: {commit_message}"
                )
                return

        # Avoid checks for the merge automation users.
        if author in {"ffxbld", "seabld", "tbirdbld", "cltbld"}:
            return

        # Match against [PATCH] and [PATCH n/m].
        if "[PATCH" in firstline:
            self.commit_message_issues.append(
                "Revision contains git-format-patch '[PATCH]' cruft. Use "
                f"git-format-patch -k to avoid this: {commit_message}"
            )
            return

        if INVALID_REVIEW_FLAG_RE.search(firstline):
            self.commit_message_issues.append(
                f"Revision contains 'r?' in the commit message. Please use 'r=' instead: {commit_message}"
            )
            return

        if firstline.lower().startswith("wip:"):
            self.commit_message_issues.append(
                f"Revision seems to be marked as WIP: {commit_message}"
            )
            return

        if any(regex.search(firstline) for regex in ACCEPTABLE_MESSAGE_FORMAT_RES):
            # Exit if the commit message matches any of our acceptable formats.
            # Conditions after this are failure states.
            return

        if firstline.lower().startswith(("back", "revert")):
            # Purposely ambiguous: it's ok to say "backed out rev N" or
            # "reverted to rev N-1"
            self.commit_message_issues.append(
                f"Backout revision needs a bug number or a rev id: {commit_message}"
            )
            return

        self.commit_message_issues.append(
            f"Revision needs 'Bug N' or 'No bug' in the commit message: {commit_message}"
        )

    def result(self) -> str | None:
        """Calculate and return the result of the check."""
        if not self.ignore_bad_commit_message and self.commit_message_issues:
            return ", ".join(self.commit_message_issues)


@dataclass
class WPTSyncCheck(PatchCollectionCheck):
    """Check the WPTSync bot is only pushing changes to relevant subset of the tree."""

    @override
    @classmethod
    def name(cls) -> str:
        return "WPTSyncCheck"

    @override
    @classmethod
    def description(cls) -> str:
        return "Check the WPTSync bot is only pushing changes to relevant subset of the tree."

    wpt_disallowed_files: list[str] = field(default_factory=list)

    def next_diff(self, patch_helper: PatchHelper):
        """Check each diff to assert the WPTSync bot is only updating allowed files."""
        if self.push_user_email != "wptsync@mozilla.com":
            return

        diffs = rs_parsepatch.get_diffs(patch_helper.get_diff())
        for parsed_diff in diffs:
            filename = parsed_diff["filename"]
            if not WPTSYNC_ALLOWED_PATHS_RE.match(filename):
                self.wpt_disallowed_files.append(filename)

    def result(self) -> str | None:
        """Return an error if the WPTSync bot touched disallowed files."""
        if self.wpt_disallowed_files:
            return (
                "Revision has WPTSync bot making changes to disallowed files "
                f"{wrap_filenames(self.wpt_disallowed_files)}."
            )


BMO_SKIP_HINT = "Use `SKIP_BMO_CHECK` in your commit message to push anyway."

BUG_REFERENCES_BMO_ERROR_TEMPLATE = (
    "Could not contact BMO to check for security bugs referenced in commit message. "
    f"{BMO_SKIP_HINT}. Error: {{error}}."
)


@dataclass
class BugReferencesCheck(PatchCollectionCheck):
    """Prevent commit messages referencing non-public bugs from try."""

    bug_ids: set[int] = field(default_factory=set)
    skip_check: bool = False

    def next_diff(self, patch_helper: PatchHelper):
        """Parse each diff for bug references information.

        If `SKIP_BMO_CHECK` is detected in any commit message, set the
        `skip_check` flag so the flag is disabled.
        """
        commit_message = patch_helper.get_commit_description()

        # Skip the check if the `skip_check` flag is set.
        if self.skip_check or "SKIP_BMO_CHECK" in commit_message:
            self.skip_check = True
            return

        self.bug_ids |= set(parse_bugs(commit_message))

    def result(self) -> str | None:
        """Ensure all bug numbers detected in commit messages reference public bugs."""
        if self.skip_check or not self.bug_ids:
            return

        try:
            found_bugs = search_bugs(self.bug_ids)
        except requests.exceptions.RequestException as exc:
            return BUG_REFERENCES_BMO_ERROR_TEMPLATE.format(error=str(exc))

        invalid_bugs = self.bug_ids - found_bugs
        if not invalid_bugs:
            return

        # Check a single bug to determine which error to return.
        bug_id = invalid_bugs.pop()
        try:
            status_code = get_status_code_for_bug(bug_id)
        except requests.exceptions.RequestException as exc:
            return BUG_REFERENCES_BMO_ERROR_TEMPLATE.format(error=str(exc))

        if status_code == 401:
            return (
                f"Your commit message references bug {bug_id}, which is currently private. To avoid "
                "disclosing the nature of this bug publicly, please remove the affected bug ID "
                f"from the commit message. {BMO_SKIP_HINT}"
            )

        if status_code == 404:
            return (
                f"Your commit message references bug {bug_id}, which does not exist. "
                f"Please check your commit message and try again. {BMO_SKIP_HINT}"
            )

        return (
            f"While checking if bug {bug_id} in your commit message is a security bug, "
            f"an error occurred and the bug could not be verified. {BMO_SKIP_HINT}"
        )


@dataclass
class PatchCollectionAssessor:
    """Assess pushes for landing issues."""

    patch_helpers: Iterable[PatchHelper]
    push_user_email: str | None = None

    def run_patch_collection_checks(
        self,
        patch_collection_checks: list[type[PatchCollectionCheck]],
        patch_checks: list[type[PatchCheck]],
    ) -> list[str]:
        """Execute the set of checks on the diffs, returning a list of issues.

        `patch_collection_checks` specifies the collection-wide checks to run on the
        `patch_helpers`. `patch_checks` specifies the checks to run on individual
        patches.
        """
        issues = []

        checks = [check(self.push_user_email) for check in patch_collection_checks]

        for patch_helper in self.patch_helpers:
            # Pass the patch information into the push-wide check.
            for check in checks:
                check.next_diff(patch_helper)

            parsed_diff = rs_parsepatch.get_diffs(patch_helper.get_diff())

            author, email = patch_helper.parse_author_information()

            # Run diff-wide checks.
            diff_assessor = DiffAssessor(
                author=author,
                email=email,
                commit_message=patch_helper.get_commit_description(),
                parsed_diff=parsed_diff,
            )
            if diff_issues := diff_assessor.run_diff_checks(patch_checks):
                issues.extend(diff_issues)

        # Collect the result of the push-wide checks.
        for check in checks:
            if issue := check.result():
                issues.append(issue)

        return issues


ALL_STACK_CHECKS = PatchCollectionCheck.__subclasses__()
ALL_COMMIT_CHECKS = PatchCheck.__subclasses__()
ALL_CHECKS = ALL_COMMIT_CHECKS + ALL_STACK_CHECKS


class LandingChecks:
    """Utility class to run landing checks (a.k.a. hooks) on a list of commits."""

    requester_email: str

    def __init__(self, requester_email: str):  # noqa: ANN001
        self.requester_email = requester_email

    def run(
        self,
        hooks: list[str] | list[type[PatchCheck] | type[PatchCollectionCheck]],
        patches: list[PatchHelper],
    ) -> list[str]:
        """Run landing checks on a stack of patches.

        Parameters:

        hooks: list[str] | list[type[PatchCheck] | type[PatchCollectionCheck]]
            Either
                - a list of strings of check names, or
                - a list of check types (e.g., ALL_STACK_CHECKS or ALL_COMMIT_CHECKS).

        patches: list[PatchHelper]
            a list of patches to check

        Returns:
            list[str]: a list of error messages.
        """
        # Flatten the list of hooks to name strings.
        hook_names = [chk if isinstance(chk, str) else chk.__name__ for chk in hooks]

        commit_checks = [chk for chk in ALL_COMMIT_CHECKS if chk.__name__ in hook_names]
        stack_checks = [chk for chk in ALL_STACK_CHECKS if chk.__name__ in hook_names]

        assessor = PatchCollectionAssessor(
            patches, push_user_email=self.requester_email
        )
        return assessor.run_patch_collection_checks(
            patch_collection_checks=stack_checks, patch_checks=commit_checks
        )
