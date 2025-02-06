import datetime
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from lando.main.scm.exceptions import SCMException
from lando.main.scm.git import GitSCM


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

    scm.update_repo(str(git_repo), target_cs)

    current_commit = subprocess.run(
        ["git", "rev-parse", "--branch", "HEAD"],
        cwd=str(clone_path),
        capture_output=True,
    ).stdout
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(clone_path), capture_output=True
    ).stdout
    assert (
        current_commit == original_commit
    ), f"Not on original_commit {original_commit} updating repo: {current_commit}"


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

    # breakpoint()
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


def test_GitSCM_git_run_redact_url_userinfo(git_repo: Path):
    scm = GitSCM(str(git_repo))
    userinfo = "user:password"
    with pytest.raises(SCMException) as exc:
        scm.push(
            f"http://{userinfo}@this-shouldn-t-resolve-otherwise-this-will-timeout-and-this-test-will-take-longer/some/repo"
        )

    assert userinfo not in exc.value.out
    assert userinfo not in exc.value.err
    assert userinfo not in str(exc.value)
    assert userinfo not in repr(exc.value)
    assert "[REDACTED]" in str(exc.value)


def _create_git_commit(request: pytest.FixtureRequest, clone_path: Path):
    new_file = clone_path / "new_file"
    new_file.write_text(request.node.name, encoding="utf-8")

    subprocess.run(["git", "add", new_file.name], cwd=str(clone_path), check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "adding new_file",
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
