import io
import os
from unittest import mock

import pytest

from lando.api.legacy.hgexports import HgPatchHelper
from lando.main.scm import (
    REQUEST_USER_ENV_VAR,
    HgCommandError,
    HgException,
    HgSCM,
    PatchConflict,
    ScmInternalServerError,
    ScmLostPushRace,
    ScmPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
    hglib,
)
from lando.main.scm.abstract_scm import AbstractSCM


def test_integrated_hgrepo_clean_repo(hg_clone):
    # Test is long and checks various repo cleaning cases as the startup
    # time for anything using `hg_clone` fixture is very long.
    repo = HgSCM(hg_clone.strpath)

    with repo.for_pull(), hg_clone.as_cwd():
        # Create a draft commits to clean.
        new_file = hg_clone.join("new-file.txt")
        new_file.write("text", mode="w+")
        repo.run_hg_cmds(
            [["add", new_file.strpath], ["commit", "-m", "new draft commit"]]
        )
        assert repo.run_hg_cmds([["outgoing"]])

        # Dirty the working directory.
        new_file.write("Extra data", mode="a")
        assert repo.run_hg_cmds([["status"]])

        # Can clean working directory without nuking commits
        repo.clean_repo(strip_non_public_commits=False)
        assert repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])

        # Dirty the working directory again.
        new_file.write("Extra data", mode="a")
        assert repo.run_hg_cmds([["status"]])

        # Cleaning should remove commit and clean working directory.
        repo.clean_repo()
        with pytest.raises(HgCommandError, match="no changes found"):
            repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])

        # Create a commit and dirty the directory before exiting
        # the context manager as entering a new context should
        # provide a clean repo.
        new_file.write("text", mode="w+")
        repo.run_hg_cmds(
            [["add", new_file.strpath], ["commit", "-m", "new draft commit"]]
        )
        new_file.write("extra data", mode="a")
        assert repo.run_hg_cmds([["outgoing"]])
        assert repo.run_hg_cmds([["status"]])

    with repo.for_pull(), hg_clone.as_cwd():
        # New context should be clean.
        with pytest.raises(HgCommandError, match="no changes found"):
            repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])


def test_integrated_hgrepo_can_log(hg_clone):
    repo = HgSCM(hg_clone.strpath)
    with repo.for_pull():
        assert repo.run_hg_cmds([["log"]])


PATCH_WITH_CONFLICT = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
Add to a file that doesn't exist
diff --git a/not-real.txt b/not-real.txt
--- a/not-real.txt
+++ b/not-real.txt
@@ -1,1 +1,2 @@
 TEST
+This line doesn't exist
""".strip()


PATCH_DELETE_NO_NEWLINE_FILE = """
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
file removed

diff --git a/test-file b/test-file
deleted file mode 100644
--- a/test-file
+++ /dev/null
@@ -1,1 +0,0 @@
-hello\r
\\ No newline at end of file
""".strip()

PATCH_NORMAL = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()

PATCH_UNICODE = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
Bug 1 - こんにちは; r?cthulhu
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()


def test_integrated_hgrepo_patch_conflict_failure(hg_clone):
    repo = HgSCM(hg_clone.strpath)

    # Patches with conflicts should raise a proper PatchConflict exception.
    with pytest.raises(PatchConflict), repo.for_pull():
        ph = HgPatchHelper(io.StringIO(PATCH_WITH_CONFLICT))
        repo.apply_patch(
            ph.get_diff(),
            ph.get_commit_description(),
            ph.get_header("User"),
            ph.get_header("Date"),
        )


@pytest.mark.parametrize(
    "name, patch",
    (
        ("normal", PATCH_NORMAL),
        ("unicode", PATCH_UNICODE),
    ),
)
def test_integrated_hgrepo_patch_success(name, patch, hg_clone):
    repo = HgSCM(hg_clone.strpath)

    with repo.for_pull():
        ph = HgPatchHelper(io.StringIO(patch))
        repo.apply_patch(
            ph.get_diff(),
            ph.get_commit_description(),
            ph.get_header("User"),
            ph.get_header("Date"),
        )
        # Commit created.
        assert repo.run_hg(
            ["outgoing"]
        ), f"No outgoing commit after {name} patch has been applied"


def test_integrated_hgrepo_patch_hgimport_fail_success(monkeypatch, hg_clone):
    repo = HgSCM(hg_clone.strpath)

    original_run_hg = repo.run_hg

    def run_hg_conflict_on_import(*args):
        if args[0] == "import":
            raise hglib.error.CommandError(
                (),
                1,
                b"",
                b"forced fail: hunk FAILED -- saving rejects to file",
            )
        return original_run_hg(*args)

    run_hg = mock.MagicMock()
    run_hg.side_effect = run_hg_conflict_on_import
    monkeypatch.setattr(repo, "run_hg", run_hg_conflict_on_import)

    with repo.for_pull():
        ph = HgPatchHelper(io.StringIO(PATCH_NORMAL))
        repo.apply_patch(
            ph.get_diff(),
            ph.get_commit_description(),
            ph.get_header("User"),
            ph.get_header("Date"),
        )
        # Commit created.
        assert repo.run_hg(
            ["outgoing"]
        ), "No outgoing commit after non-hg importable patch has been applied"


def test_integrated_hgrepo_apply_patch_newline_bug(hg_clone):
    """Test newline bug in Mercurial

    See https://bugzilla.mozilla.org/show_bug.cgi?id=1541181 for context.
    """
    repo = HgSCM(hg_clone.strpath)

    with repo.for_pull(), hg_clone.as_cwd():
        # Create a file without a new line and with a trailing `\r`
        # Note that to reproduce this bug, this file needs to already exist
        # in the repo and not be imported in a patch.
        new_file = hg_clone.join("test-file")
        new_file.write(b"hello\r", mode="wb")
        repo.run_hg_cmds(
            [["add", new_file.strpath], ["commit", "-m", "adding file"], ["push"]]
        )
        ph = HgPatchHelper(io.StringIO(PATCH_DELETE_NO_NEWLINE_FILE))
        repo.apply_patch(
            ph.get_diff(),
            ph.get_commit_description(),
            ph.get_header("User"),
            ph.get_header("Date"),
        )
        # Commit created.
        assert "file removed" in str(repo.run_hg(["outgoing"]))


def test_hg_exceptions():
    """Ensure the correct exception is raised if a particular snippet is present."""
    snippet_exception_mapping = {
        b"abort: push creates new remote head": ScmLostPushRace,
        b"APPROVAL REQUIRED!": TreeApprovalRequired,
        b"is CLOSED!": TreeClosed,
        b"unresolved conflicts (see hg resolve": PatchConflict,
        b"timed out waiting for lock held by": ScmPushTimeoutException,
        b"abort: HTTP Error 500: Internal Server Error": ScmInternalServerError,
    }

    for snippet, exception in snippet_exception_mapping.items():
        exc = hglib.error.CommandError((), 1, b"", snippet)
        with pytest.raises(exception):
            raise HgException.from_hglib_error(exc)


def test_hgrepo_request_user(hg_clone):
    """Test that the request user environment variable is set and unset correctly."""
    repo = HgSCM(hg_clone.strpath)
    request_user_email = "test@example.com"

    assert REQUEST_USER_ENV_VAR not in os.environ
    with repo.for_push(request_user_email):
        assert REQUEST_USER_ENV_VAR in os.environ
        assert os.environ[REQUEST_USER_ENV_VAR] == "test@example.com"
    assert REQUEST_USER_ENV_VAR not in os.environ


@pytest.mark.parametrize(
    "scm,repo_fixture_name,expected",
    (
        (HgSCM, "hg_clone", True),
        (HgSCM, "tmpdir", False),
    ),
)
def test_repo_is_supported(
    scm: AbstractSCM, repo_fixture_name: str, expected: bool, request
):
    repo = request.getfixturevalue(repo_fixture_name)
    assert (
        scm.repo_is_supported(repo) == expected
    ), f"{scm} did not correctly report support for {repo.str.path}"
