import base64
import datetime
import io
import re
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from lando.main.scm.exceptions import SCMException
from lando.main.scm.git import GitSCM
from lando.main.scm.helpers import GitPatchHelper


@pytest.mark.parametrize(
    "path,expected",
    (
        ("/non-existent-path", False),
        ("/tmp", False),
        (None, True),  # generate a default path
    ),
)
def test_GitSCM_is_initialised(git_repo: Path, path: str, expected: bool):
    if not path:
        path = str(git_repo)
    scm = GitSCM(path)
    assert scm.repo_is_initialized == expected


def test_GitSCM_str(git_repo: Path):
    path = str(git_repo)
    scm = GitSCM(path)
    scm_str = str(scm)
    assert "Git" in scm_str
    assert path in scm_str


@pytest.mark.parametrize(
    "repo_path,expected",
    (
        ("", True),
        ("/", False),
    ),
)
def test_GitSCM_repo_is_supported(repo_path: str, expected: bool, git_repo: Path):
    scm = GitSCM
    if not repo_path:
        repo_path = str(git_repo)
    assert (
        scm.repo_is_supported(repo_path) == expected
    ), f"{scm} did not correctly report support for {repo_path}"


def test_GitSCM_clone(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    scm = GitSCM(str(clone_path))

    mock_git_run = _monkeypatch_scm(monkeypatch, scm, "_git_run")

    scm.clone(str(git_repo))

    mock_git_run.assert_any_call("clone", str(git_repo), str(clone_path), cwd="/")
    assert clone_path.exists(), f"New git clone {clone_path} wasn't created"
    assert (
        clone_path / ".git"
    ).exists(), f"New git clone {clone_path} doesn't contain a .git directory"


@pytest.mark.parametrize(
    "strip_non_public_commits",
    [True, False],
)
def test_GitSCM_clean_repo(
    git_repo: Path,
    git_setup_user: Callable,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    strip_non_public_commits: bool,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    original_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(clone_path), capture_output=True
    ).stdout

    # Create an empty commit that we expect to see rewound, too
    subprocess.run(
        [
            "git",
            "commit",
            "--fixup",
            "reword:HEAD",
            "--no-edit",
        ],
        cwd=str(clone_path),
        check=True,
    )
    # Those two command should not raise exceptions
    new_file = _create_git_commit(request, clone_path)

    new_untracked_file = clone_path / "new_untracked_file"
    new_untracked_file.write_text("test", encoding="utf-8")

    mock_git_run = _monkeypatch_scm(monkeypatch, scm, "_git_run")

    scm.clean_repo(strip_non_public_commits=strip_non_public_commits)

    mock_git_run.assert_called_with("clean", "-fdx", cwd=str(clone_path))
    if strip_non_public_commits:
        mock_git_run.assert_any_call(
            "reset", "--hard", f"origin/{scm.default_branch}", cwd=str(clone_path)
        )
        current_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(clone_path), capture_output=True
        ).stdout
        assert (
            current_commit == original_commit
        ), f"Not on original_commit {original_commit} after using strip_non_public_commits: {current_commit}"

    assert (
        strip_non_public_commits != new_file.exists()
    ), f"strip_non_public_commits not honoured for {new_file}"


@pytest.mark.parametrize(
    "current_gitattributes,new_gitattributes",
    (
        (None, "* !diff"),
        ("* !diff", None),
        ("", "* !diff"),
        ("* !diff", "* !diff"),
        ("* !diff", ""),
    ),
)
def test_GitSCM_clean_repo_gitattributes(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    current_gitattributes: str | None,
    new_gitattributes: str | None,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))
    git_setup_user(str(clone_path))

    attributes_file: Path = clone_path / ".git" / "info" / "attributes"

    if current_gitattributes is None:
        attribute_mtime = 0
    else:
        with open(attributes_file, "w") as file:
            file.write(current_gitattributes)
        attribute_mtime = attributes_file.stat().st_mtime
        # Wait a bit so the next file modification has a different mtime.
        # sleep(0.01)

    scm.clean_repo(attributes_override=new_gitattributes)

    new_attribute_mtime = attributes_file.stat().st_mtime

    expected_gitattributes = (
        # We want to allow empty strings to go through, so we need an explicit
        # comparison to None.
        new_gitattributes
        if new_gitattributes is not None
        else current_gitattributes
    )
    with open(attributes_file, "r") as file:
        assert (
            file.read() == expected_gitattributes
        ), f"{attributes_file} contents does not match expected overrides"

    if new_gitattributes == current_gitattributes or new_gitattributes is None:
        assert (
            new_attribute_mtime == attribute_mtime
        ), f"{attributes_file} with same content should not have been modified"


def remove_git_version_from_patch(patch: str) -> str:
    """Return a patch with the Git version stripped."""
    return re.sub(r"\d+(\.\d+)+$", "", patch)


def test_GitSCM_apply_get_patch(git_repo: Path, git_patch: Callable):
    scm = GitSCM(str(git_repo))

    # Choose the patch to apply wisely: the original patch may have a `[PATCH]`
    # in the subject that will get stripped on on application and subsequent export,
    # leading to a spurious test failure when comparing output to expected.
    patch = git_patch()

    ph = GitPatchHelper(io.StringIO(patch))

    author_name, author_email = ph.parse_author_information()
    author = f"{author_name} <{author_email}>"
    scm.apply_patch(
        ph.get_diff(), ph.get_commit_description(), author, ph.get_timestamp()
    )

    commit = scm.describe_commit()

    expected_patch = patch
    new_patch = scm.get_patch(commit.hash)

    assert new_patch, f"Empty patch unexpectedly generated for {commit.hash}"

    # The git version stamp varies. Strip it from the output before comparing.
    no_version_patch = remove_git_version_from_patch(new_patch)

    assert no_version_patch == expected_patch


def test_GitSCM_apply_get_patch_merge(
    git_repo: Path,
    git_patch: Callable,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    scm = GitSCM(str(git_repo))

    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    main_branch = "main"
    scm = GitSCM(str(clone_path), default_branch=main_branch)
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    # Create a new commit on a branch for merging
    _create_git_commit(request, clone_path)
    scm.head_ref()

    # Switch to target branch and create another commit.
    target_branch = "target"
    subprocess.run(
        ["git", "switch", "-c", target_branch, "HEAD^"], cwd=str(clone_path), check=True
    )

    # Choose the patch to apply wisely: the original patch may have a `[PATCH]`
    # in the subject that will get stripped on on application and subsequent export,
    # leading to a spurious test failure when comparing output to expected.
    patch = git_patch()
    ph = GitPatchHelper(io.StringIO(patch))
    author_name, author_email = ph.parse_author_information()
    author = f"{author_name} <{author_email}>"
    scm.apply_patch(
        ph.get_diff(), ph.get_commit_description(), author, ph.get_timestamp()
    )

    # Merge feature into main
    subprocess.run(["git", "switch", main_branch], cwd=str(clone_path), check=True)
    strategy = "theirs"
    commit_msg = f"Merge main into feature with strategy {strategy}"
    merge_commit = scm.merge_onto(commit_msg, target_branch, strategy)

    commit = scm.describe_commit(merge_commit)
    merge_patch_helper = scm.get_patch_helper(commit.hash)

    assert merge_patch_helper is None


def test_GitSCM_apply_patch_bytes(git_repo: Path, git_patch: Callable):
    scm = GitSCM(str(git_repo))

    # Get patch content as bytes
    patch_str = git_patch()
    patch_bytes = patch_str.encode("utf-8")

    # Apply patch using the new method
    scm.apply_patch_bytes(patch_bytes)

    commit = scm.describe_commit()

    expected_patch = patch_str
    new_patch = scm.get_patch(commit.hash)

    assert new_patch, f"Empty patch unexpectedly generated for {commit.hash}"

    # The git version stamp varies. Strip it from the output before comparing.
    no_version_patch = remove_git_version_from_patch(new_patch)

    assert no_version_patch == expected_patch


def test_GitSCM_apply_patch_bytes_base64(git_repo: Path, git_patch: Callable):
    scm = GitSCM(str(git_repo))

    patch_str = git_patch()
    patch_b64 = base64.b64encode(patch_str.encode("utf-8")).decode("ascii")

    patch_bytes = base64.b64decode(patch_b64)
    scm.apply_patch_bytes(patch_bytes)

    commit = scm.describe_commit()

    expected_patch = patch_str
    new_patch = scm.get_patch(commit.hash)

    assert new_patch, f"Empty patch unexpectedly generated for {commit.hash}"

    # The git version stamp varies. Strip it from the output before comparing.
    no_version_patch = remove_git_version_from_patch(new_patch)

    assert no_version_patch == expected_patch


def test_GitSCM_apply_patch_bytes_aborts_on_failure(
    git_repo: Path,
    git_patch: Callable,
):
    scm = GitSCM(str(git_repo))

    rebase_apply = Path(git_repo) / ".git" / "rebase-apply"

    # Ensure the repo is clean.
    assert not rebase_apply.exists()

    # Apply a bad patch.
    with pytest.raises(SCMException):
        scm.apply_patch_bytes(b"blah")

    # Ensure the `rebase-apply` directory is gone.
    assert (
        not rebase_apply.exists()
    ), "`rebase-apply` dir was not cleaned up after failed git am"

    # Create `rebase-apply` directory.
    rebase_apply.mkdir()

    # Create a good patch.
    good_patch_str = git_patch()
    good_patch_b64 = base64.b64encode(good_patch_str.encode("utf-8")).decode("ascii")
    good_patch_bytes = base64.b64decode(good_patch_b64)

    # Apply a good patch with failed `git am` state present.
    scm.apply_patch_bytes(good_patch_bytes)

    # Ensure the `rebase-apply` directory is gone.
    assert (
        not rebase_apply.exists()
    ), "`rebase-apply` dir was not cleaned up after failed git am"

    commit = scm.describe_commit()
    assert commit.hash, "Valid patch did not land after recovering from failure"


DIFF_WITH_IGNORED_JSON = """\
diff --git a/ignored.json b/ignored.json
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/ignored.json
@@
+{"key": "value"}
"""


def test_GitSCM_apply_patch_includes_ignored_files(
    git_repo: Path,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    git_setup_user: Callable,
):
    scm = GitSCM(str(git_repo))

    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    main_branch = "main"
    scm = GitSCM(str(clone_path), default_branch=main_branch)
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    # Add .gitignore that ignores `ignored.json`.
    (clone_path / ".gitignore").write_text("ignored.json\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=clone_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add .gitignore"], cwd=clone_path, check=True
    )

    # Apply the patch.
    commit_msg = "add ignored.json"
    author = "Patch Author <author@example.com>"
    commit_date = "Thu, 1 Jan 1970 00:00:00 +0000"
    scm.apply_patch(DIFF_WITH_IGNORED_JSON, commit_msg, author, commit_date)

    # Check that ignored.json is tracked
    result = subprocess.run(
        ["git", "ls-files", "ignored.json"],
        cwd=clone_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert result == "ignored.json", "`ignored.json` was not tracked after patch apply."

    # Check that the commit message matches.
    last_commit_msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=clone_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert last_commit_msg == commit_msg, "Commit message did not match."

    # Check that ignored.json is part of that commit.
    files_in_commit = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", "HEAD"],
        cwd=clone_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert (
        "ignored.json" in files_in_commit
    ), "`ignored.json` not found in committed files."


def test_GitSCM_describe_commit(git_repo: Path):
    scm = GitSCM(str(git_repo))

    commit = scm.describe_commit()
    prev_commit = scm.describe_commit("HEAD^")

    assert commit.hash, "Hash missing"
    assert len(commit.hash) == 40, "Incorrect hash length"
    assert commit.parents, "Non-initial commit should have parents"
    assert commit.author == "Test User <test@example.com>"
    assert commit.datetime == datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
    assert (
        commit.desc
        == """add another file
"""
    )
    assert len(commit.files) == 1
    assert "test.txt" in commit.files

    assert prev_commit.hash, "Hash missing"
    assert not prev_commit.parents, "Initial commit should not have parents"
    assert prev_commit.author == "Test User <test@example.com>"
    assert prev_commit.datetime == datetime.datetime.fromtimestamp(
        0, datetime.timezone.utc
    )
    assert (
        prev_commit.desc
        == """initial commit
"""
    )
    assert len(prev_commit.files) == 1
    assert "README" in prev_commit.files


def test_GitSCM_describe_local_changes(
    git_repo: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    file1 = _create_git_commit(request, clone_path)
    file2 = _create_git_commit(request, clone_path)

    changes = scm.describe_local_changes()

    assert file1.name in changes[0].files
    assert file2.name in changes[1].files


def test_GitSCM_describe_local_changes_with_explicit_target_cset(
    git_repo: Path,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    # Clone the repo into a new directory
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    # Create a base commit
    base_commit_file = _create_git_commit(request, clone_path)
    base_commit_sha = scm.head_ref()

    # Create two more commits
    second_commit_file = _create_git_commit(request, clone_path)
    third_commit_file = _create_git_commit(request, clone_path)

    # Now get commits since the base commit explicitly
    commits = scm.describe_local_changes(base_cset=base_commit_sha)

    # We expect exactly two new commits
    assert len(commits) == 2, "Expected exactly two commits since the base commit."

    changed_files = [file for commit in commits for file in commit.files]

    assert second_commit_file.name in changed_files
    assert third_commit_file.name in changed_files
    assert (
        base_commit_file.name not in changed_files
    ), "Base commit file should not appear in local changes."


@pytest.mark.parametrize("target_cs", [None, "main", "dev", "git-ref"])
def test_GitSCM_update_repo(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    target_cs: str,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    original_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(clone_path),
        capture_output=True,
    ).stdout

    if target_cs == "git-ref":
        # Special case for a naked git reference
        target_cs = original_commit.decode("utf-8").strip()
    elif target_cs:
        original_commit = subprocess.run(
            ["git", "rev-parse", f"origin/{target_cs}"],
            cwd=str(clone_path),
            capture_output=True,
        ).stdout

    # Create an empty commit that we expect to see rewound, too
    subprocess.run(
        [
            "git",
            "commit",
            "--fixup",
            "reword:HEAD",
            "--no-edit",
        ],
        cwd=str(clone_path),
        check=True,
    )
    _create_git_commit(request, clone_path)

    attributes_override = "some/weird/file diff"

    scm.update_repo(str(git_repo), target_cs, attributes_override=attributes_override)

    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(clone_path), capture_output=True
    ).stdout
    assert (
        current_commit == original_commit
    ), f"Not on original_commit {original_commit} updating repo: {current_commit}"

    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(clone_path),
        capture_output=True,
    ).stdout
    assert current_branch.startswith(
        b"lando-"
    ), f"Not on a work branch after update_repo: {current_branch}"

    gitattributes = clone_path / ".git" / "info" / "attributes"
    with open(gitattributes, "r") as f:
        assert (
            f.read() == attributes_override
        ), f".gitattributes override not in {gitattributes}"


@pytest.mark.parametrize(
    "on_parent",
    [
        False,
        # XXX: changeset_descriptions doesn't work when update_repo has been used with a commit rev
        # as the target_cs. This is generally used when grafting a revision for Try, which
        # doesn't use changeset_descriptions, so we tolerate this for now.
        #
        # True,
    ],
)
def test_GitSCM_changeset_descriptions_on_workbranch(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    on_parent: str,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()
    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    target_cs = ""
    if on_parent:
        target_cs = scm.describe_commit().parents[0]

    scm.update_repo(str(git_repo), target_cs)

    _create_git_commit(request, clone_path)

    assert (
        len(scm.changeset_descriptions()) == 1
    ), "Incorrect number of commit from the local changeset"


@pytest.mark.parametrize("push_target", [None, "main", "dev"])
def test_GitSCM_push(
    git_repo: Path,
    git_setup_user: Callable,
    monkeypatch: pytest.MonkeyPatch,
    push_target: Optional[str],
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    default_branch = "dev"
    scm = GitSCM(str(clone_path), default_branch=default_branch)
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    _create_git_commit(request, clone_path)

    new_untracked_file = clone_path / "new_untracked_file"
    new_untracked_file.write_text("test", encoding="utf-8")

    mock_git_run = _monkeypatch_scm(monkeypatch, scm, "_git_run")

    scm.push(str(git_repo), push_target)

    if not push_target:
        push_target = default_branch
    mock_git_run.assert_called_with(
        "push", str(git_repo), f"HEAD:{push_target}", cwd=str(clone_path)
    )


def test_GitSCM_push_get_github_token(git_repo: Path):
    scm = GitSCM(str(git_repo))
    scm._git_run = MagicMock()
    scm._get_github_token = MagicMock()
    scm._get_github_token.side_effect = ["ghs_yolo"]

    scm.push("https://github.com/some/repo")

    assert scm._git_run.call_count == 1, "_git_run wasn't called when pushing"
    assert (
        scm._get_github_token.call_count == 1
    ), "_get_github_token wasn't called when pushing to a github-like URL"
    assert (
        "git:ghs_yolo@github.com" in scm._git_run.call_args[0][1]
    ), "github token not found in rewritten push_path"


@pytest.mark.parametrize(
    "string,should_be_redacted",
    [("user:password", True), ("user", False), ("guage@2x.png", False)],
)
def test_GitSCM_git_run_redact_url_userinfo(
    git_repo: Path, string: str, should_be_redacted: bool
):
    scm = GitSCM(str(git_repo))
    with pytest.raises(SCMException) as exc:
        scm.push(
            f"http://{string}@this-shouldn-t-resolve-otherwise-this-will-timeout-and-this-test-will-take-longer/some/repo"
        )

    if should_be_redacted:
        assert string not in exc.value.out
        assert string not in exc.value.err
        assert string not in str(exc.value)
        assert string not in repr(exc.value)
        assert "[REDACTED]" in str(exc.value)
    else:
        assert string in str(exc.value)
        assert string in repr(exc.value)
        assert "[REDACTED]" not in str(exc.value)


def _create_git_commit(request: pytest.FixtureRequest, clone_path: Path):
    new_file = clone_path / str(uuid.uuid4())
    new_file.write_text(request.node.name, encoding="utf-8")

    subprocess.run(["git", "add", new_file.name], cwd=str(clone_path), check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            f"No bug: adding {new_file}",
            "--author",
            f"{request.node.name} <pytest@lando>",
        ],
        cwd=str(clone_path),
        check=True,
    )

    return new_file


def _monkeypatch_scm(monkeypatch, scm: GitSCM, method: str) -> MagicMock:
    """
    Mock a method on `scm` to test the call, but let it continue with its original side
    effect, so we can test that it's correct, too.

    Returns:
    MagicMock: The mock object.
    """
    original = scm.__getattribute__(method)
    mock = MagicMock()
    mock.side_effect = original
    monkeypatch.setattr(scm, method, mock)
    return mock


@pytest.mark.parametrize("strategy", [None, "ours", "theirs"])
def test_GitSCM_merge_onto(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    strategy: Optional[str],
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    main_branch = "main"
    scm = GitSCM(str(clone_path), default_branch=main_branch)
    scm.clone(str(git_repo))

    git_setup_user(str(clone_path))

    # Create a new commit on a branch for merging
    main_commit_file = _create_git_commit(request, clone_path)
    main_commit = scm.head_ref()

    # Switch to target branch and create another commit.
    target_branch = "target"
    subprocess.run(
        ["git", "switch", "-c", target_branch, "HEAD^"], cwd=str(clone_path), check=True
    )
    target_commit_file = _create_git_commit(request, clone_path)
    target_commit = scm.head_ref()

    # Merge feature into main
    subprocess.run(["git", "switch", main_branch], cwd=str(clone_path), check=True)
    commit_msg = f"Merge main into feature with strategy {strategy}"
    merge_commit = scm.merge_onto(commit_msg, target_branch, strategy)

    # Assert we are on the correct branch.
    current_branch = (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(clone_path),
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )
    current_sha = scm.head_ref()
    assert (
        current_branch == main_branch
    ), "`merge_onto` incorrectly changed the current branch."
    assert (
        current_sha == merge_commit
    ), "`merge_onto` did not leave the repo on the merge commit."

    # Confirm the new commit has two parents.
    parents = (
        subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", merge_commit],
            cwd=str(clone_path),
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
        .split()
    )
    # Len is 3 here due to 2 parents + the commit itself.
    assert len(parents) == 3, f"Expected merge commit with 2 parents, got: {parents}"

    assert (
        main_commit in parents and target_commit in parents
    ), "Unexpected merge parents."
    assert (
        commit_msg in scm.changeset_descriptions()
    ), "Commit message is not found in descriptions."

    file_to_check = target_commit_file
    expected_sha = None
    if strategy == "ours":
        # The file in the merge commit should be the same as `main`.
        file_to_check = main_commit_file
        expected_sha = main_commit
    elif strategy == "theirs":
        # The file in the merge commit should be the same as `target`.
        file_to_check = target_commit_file
        expected_sha = target_commit

    # # Get the contents of the file at the merge commit.
    merged_file = subprocess.run(
        ["git", "show", f"{merge_commit}:{file_to_check.name}"],
        cwd=clone_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Get expected content based on strategy.
    if expected_sha:
        expected_content = subprocess.run(
            ["git", "show", f"{expected_sha}:{file_to_check.name}"],
            cwd=clone_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        assert all(
            {merged_file, expected_content}
        ), "File contents should be non-empty."

        assert (
            merged_file == expected_content
        ), f"File contents did not match expected for strategy {strategy}"


def test_GitSCM_merge_onto_fast_forward(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))
    git_setup_user(str(clone_path))

    # Create base commit on main.
    _create_git_commit(request, clone_path)

    # Create a feature branch and add a commit.
    subprocess.run(["git", "switch", "-c", "feature"], cwd=clone_path, check=True)
    _create_git_commit(request, clone_path)
    feature_commit = scm.head_ref()

    # Switch back to base.
    subprocess.run(["git", "switch", "main"], cwd=clone_path, check=True)
    base_commit = scm.head_ref()

    # Merge (should fast-forward).
    commit_msg = "Fast-forward merge"
    new_head = scm.merge_onto(commit_msg, feature_commit, strategy=None)

    # Check that the HEAD matches the feature commit (i.e. fast-forward happened)
    assert (
        new_head == feature_commit
    ), "Returned head for `main` should point to the same SHA as `feature`."
    assert (
        new_head != base_commit
    ), "Returned head for `main` should not point to the old base."
    assert (
        scm.head_ref() == feature_commit
    ), "Current head should point to the same SHA as `feature`."
    assert (
        scm.head_ref() != base_commit
    ), "Returned head for `main` should not point to the old base."

    # Check that no merge commit was created.
    parents = (
        subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", new_head],
            cwd=clone_path,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .split()
    )

    assert (
        len(parents) == 2
    ), "Fast-forward should have one parent (i.e. no merge commit)."


def test_GitSCM_tag(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))
    git_setup_user(str(clone_path))

    # Create a new commit and get its SHA
    _create_git_commit(request, clone_path)
    commit_sha = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=clone_path,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )

    # Tag the current commit
    tag_name = "v1.0"
    scm.tag(tag_name, None)

    # Check that the tag exists
    tag_output = (
        subprocess.run(
            ["git", "tag", "--list"], cwd=clone_path, capture_output=True, check=True
        )
        .stdout.decode()
        .splitlines()
    )

    assert tag_name in tag_output, f"New tag {tag_name} should be present in tags list."

    # Check the tag points to the expected commit
    tag_sha = (
        subprocess.run(
            ["git", "rev-list", "-n", "1", tag_name],
            cwd=clone_path,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )

    assert tag_sha == commit_sha, "Tag should point to expected commit."


def test_GitSCM_push_tag(
    git_repo: Path,
    git_setup_user: Callable,
    request: pytest.FixtureRequest,
    tmp_path: Path,
):
    clone_path = tmp_path / request.node.name
    clone_path.mkdir()

    scm = GitSCM(str(clone_path))
    scm.clone(str(git_repo))
    git_setup_user(str(clone_path))

    # Create a commit and tag it
    _create_git_commit(request, clone_path)
    tag_name = "v1.0.0"
    scm.tag(tag_name, None)

    # Push the tag
    scm.push_tag(tag_name, str(git_repo))

    # Check that the tag exists in the remote
    tag_exists = subprocess.run(
        ["git", "ls-remote", "--tags", str(git_repo), tag_name],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert tag_exists, f"Tag {tag_name} was not found in the remote repository."
