import io
import os
import subprocess
import textwrap
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from lando.api.legacy.hgexports import HgPatchHelper
from lando.main.scm import (
    REQUEST_USER_ENV_VAR,
    HgCommandError,
    HgException,
    HgSCM,
    PatchConflict,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
    hglib,
)


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
    "name, patch, expected_log",
    (
        ("normal", PATCH_NORMAL, ""),
        ("unicode", PATCH_UNICODE, "こんにちは"),
    ),
)
def test_integrated_hgrepo_patch_success(
    name: str, patch: str, expected_log: str, hg_clone
):
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

        log_output = repo.run_hg(["log"])
        assert expected_log in log_output.decode("utf-8")


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
        b"abort: push creates new remote head": SCMLostPushRace,
        b"APPROVAL REQUIRED!": TreeApprovalRequired,
        b"is CLOSED!": TreeClosed,
        b"unresolved conflicts (see hg resolve": PatchConflict,
        b"timed out waiting for lock held by": SCMPushTimeoutException,
        b"abort: HTTP Error 500: Internal Server Error": SCMInternalServerError,
        (
            b"remote: could not complete push due to pushlog operational errors; "
            b"please retry, and file a bug if the issue persists"
        ): SCMInternalServerError,
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
    "repo_path,expected",
    (
        ("", True),
        ("/", False),
    ),
)
def test_repo_is_supported(repo_path: str, expected: bool, hg_clone):
    scm = HgSCM
    if not repo_path:
        repo_path = hg_clone.strpath
    assert (
        scm.repo_is_supported(repo_path) == expected
    ), f"{scm} did not correctly report support for {repo_path}"


def test_HgSCM__extract_error_data():
    exception_message = textwrap.dedent(
        """\
    patching file toolkit/moz.configure
    Hunk #1 FAILED at 2075
    Hunk #2 FAILED at 2325
    Hunk #3 FAILED at 2340
    3 out of 3 hunks FAILED -- saving rejects to file toolkit/moz.configure.rej
    patching file moz.configure
    Hunk #1 FAILED at 239
    Hunk #2 FAILED at 250
    2 out of 2 hunks FAILED -- saving rejects to file moz.configure.rej
    patching file a/b/c.d
    Hunk #1 FAILED at 656
    1 out of 1 hunks FAILED -- saving rejects to file a/b/c.d.rej
    patching file d/e/f.g
    Hunk #1 FAILED at 6
    1 out of 1 hunks FAILED -- saving rejects to file d/e/f.g.rej
    patching file h/i/j.k
    Hunk #1 FAILED at 4
    1 out of 1 hunks FAILED -- saving rejects to file h/i/j.k.rej
    file G0fvb1RuMQxXNjs already exists
    1 out of 1 hunks FAILED -- saving rejects to file G0fvb1RuMQxXNjs.rej
    unable to find 'abc/def' for patching
    (use '--prefix' to apply patch relative to the current directory)
    1 out of 1 hunks FAILED -- saving rejects to file abc/def.rej
    patching file browser/locales/en-US/browser/browserContext.ftl
    Hunk #1 succeeded at 300 with fuzz 2 (offset -4 lines).
    abort: patch failed to apply"""
    )

    expected_failed_paths = [
        "toolkit/moz.configure",
        "moz.configure",
        "a/b/c.d",
        "d/e/f.g",
        "h/i/j.k",
        "G0fvb1RuMQxXNjs",
        "abc/def",
    ]

    expected_rejects_paths = [
        "toolkit/moz.configure.rej",
        "moz.configure.rej",
        "a/b/c.d.rej",
        "d/e/f.g.rej",
        "h/i/j.k.rej",
        "G0fvb1RuMQxXNjs.rej",
        "abc/def.rej",
    ]

    failed_paths, rejects_paths = HgSCM._extract_error_data(exception_message)
    assert failed_paths == expected_failed_paths
    assert rejects_paths == expected_rejects_paths


def test_HgSCM_describe_commit(hg_clone):
    scm = HgSCM(str(hg_clone))

    with scm.for_push("committer@moz.test"):
        commit = scm.describe_commit()
        prev_commit = scm.describe_commit("-2")

    assert commit.hash, "Hash missing"
    assert len(commit.hash) == 40, "Incorrect hash length"
    assert commit.parents, "Non-initial commit should have parents"
    assert commit.author == "Test User <test@example.com>"
    assert commit.datetime == datetime.fromtimestamp(0)
    assert commit.desc == """add another file"""
    assert len(commit.files) == 1
    assert "test.txt" in commit.files

    assert prev_commit.hash, "Hash missing"
    assert not prev_commit.parents, "Initial commit should not have parents"
    assert prev_commit.author == "Test User <test@example.com>"
    assert prev_commit.datetime == datetime.fromtimestamp(0)
    assert prev_commit.desc == """initial commit"""
    assert len(prev_commit.files) == 1
    assert "README" in prev_commit.files


def test_HgSCM_describe_local_changes(
    # XXX: this is a py.path, but we want to use pathlib.Path moving forwards
    hg_clone,
    request: pytest.FixtureRequest,
):
    scm = HgSCM(str(hg_clone))

    #     f"{request.node.name} <pytest@lando>",
    with scm.for_push(
        f"pytest+{request.node.name}@lando",
    ):
        file1 = _create_hg_commit(request, Path(hg_clone))
        file2 = _create_hg_commit(request, Path(hg_clone))

        changes = scm.describe_local_changes()

    assert file1.name in changes[0].files
    assert file2.name in changes[1].files


def _create_hg_commit(request: pytest.FixtureRequest, clone_path: Path):
    new_file = clone_path / str(uuid.uuid4())
    new_file.write_text(request.node.name, encoding="utf-8")

    subprocess.run(["hg", "addremove"], cwd=str(clone_path), check=True)
    subprocess.run(
        [
            "hg",
            "commit",
            "-m",
            f"adding {new_file}",
        ],
        cwd=str(clone_path),
        check=True,
    )

    return new_file


@pytest.mark.parametrize("strategy", [None, "ours", "theirs"])
def test_HgSCM_merge_onto(
    hg_clone,
    request: pytest.FixtureRequest,
    strategy: str | None,
):
    scm = HgSCM(hg_clone.strpath)

    with scm.for_push(f"pytest+{request.node.name}@lando"):
        # Start on the default branch (main)
        main_start_commit = scm.head_ref()

        # Create commits on main branch
        main_file = _create_hg_commit(request, Path(hg_clone))
        _create_hg_commit(request, Path(hg_clone))
        _create_hg_commit(request, Path(hg_clone))
        main_commit = scm.head_ref()

        # Update to start commit and create separate feature history
        subprocess.run(
            ["hg", "update", "--clean", "-r", main_start_commit],
            cwd=str(hg_clone),
            check=True,
        )

        feature_file = _create_hg_commit(request, Path(hg_clone))
        _create_hg_commit(request, Path(hg_clone))
        _create_hg_commit(request, Path(hg_clone))
        feature_commit = scm.head_ref()

        # Update back to main and merge in feature
        subprocess.run(
            ["hg", "update", "--clean", "-r", main_commit],
            cwd=str(hg_clone),
            check=True,
        )

        merge_msg = f"Merge main into feature with strategy {strategy}"
        merge_node = scm.merge_onto(merge_msg, feature_commit, strategy)

        # Check that the merge commit has two parents
        parents = (
            subprocess.run(
                ["hg", "log", "-r", merge_node, "-T", "{p1node} {p2node}"],
                cwd=str(hg_clone),
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .strip()
            .split()
        )

        assert (
            len(parents) == 2
        ), f"Expected merge commit with 2 parents, got: {parents}"
        assert (
            main_commit in parents and feature_commit in parents
        ), f"Unexpected merge parents: {parents}"

        # Pick the file and commit that should define the content
        if strategy == "ours":
            file_to_check = main_file
            expected_rev = main_commit
        elif strategy == "theirs":
            file_to_check = feature_file
            expected_rev = feature_commit
        else:
            # We don't know which content will win in normal merge,
            # so we just ensure the file exists
            file_to_check = feature_file
            expected_rev = None

        # Check the content in the merge commit
        merged_content = subprocess.run(
            ["hg", "cat", "-r", merge_node, file_to_check.name],
            cwd=str(hg_clone),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        if expected_rev:
            expected_content = subprocess.run(
                ["hg", "cat", "-r", expected_rev, file_to_check.name],
                cwd=str(hg_clone),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            assert all(
                {merged_content, expected_content}
            ), "File contents should be non-empty"

            assert (
                merged_content == expected_content
            ), f"File contents did not match expected for strategy {strategy}"
