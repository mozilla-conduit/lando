import subprocess

import pytest

from lando.main.scm import PatchConflict
from lando.main.scm.exceptions import CommitNotFound, SCMException
from lando.main.scm.git import GitSCM


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def commit_file(create_git_commit):
    def _commit_file(repo, content, message="Bug 123 - Break startup"):
        create_git_commit(repo, message=message, name="backout-test", content=content)
        return git(repo, "rev-parse", "HEAD")

    return _commit_file


def test_git_revert(git_repo, commit_file):
    scm = GitSCM(str(git_repo))
    base_tree = git(git_repo, "rev-parse", "HEAD^{tree}")
    target = commit_file(git_repo, "broken")
    with scm.for_push("hackbot@mozilla.tld"):
        scm.revert_commit(target.upper())
    assert git(git_repo, "rev-parse", "HEAD^{tree}") == base_tree
    assert git(git_repo, "show", "-s", "--format=%B") == (
        f'Revert "Bug 123 - Break startup"\n\nThis reverts commit {target}.'
    )
    assert git(git_repo, "show", "-s", "--format=%ae") == "pytest@lando.example.net"
    assert git(git_repo, "show", "-s", "--format=%ce") == "hackbot@mozilla.tld"
    assert scm.describe_commit().reverted_commit_hashes() == [target]
    assert not git(git_repo, "status", "--porcelain")


@pytest.mark.parametrize(
    "kind,exception",
    [
        ("missing", CommitNotFound),
        ("blob", CommitNotFound),
        ("tag", CommitNotFound),
        ("branch", ValueError),
        ("root", ValueError),
        ("merge", ValueError),
    ],
)
def test_git_revert_rejects_invalid_targets(git_repo, commit_file, kind, exception):
    scm = GitSCM(str(git_repo))
    target = commit_file(git_repo, "broken")
    if kind == "missing":
        target = "0" * 40
    elif kind == "blob":
        target = git(git_repo, "rev-parse", "HEAD:backout-test")
    elif kind == "tag":
        git(git_repo, "tag", "-a", "annotated", "-m", "Annotated tag")
        target = git(git_repo, "rev-parse", "annotated")
    elif kind == "branch":
        git(git_repo, "checkout", "-b", "unlanded")
        target = commit_file(git_repo, "unlanded")
        git(git_repo, "checkout", "main")
    elif kind == "root":
        target = git(git_repo, "rev-list", "--max-parents=0", "HEAD")
    elif kind == "merge":
        git(git_repo, "merge", "--no-ff", "dev", "-m", "Merge dev")
        target = scm.head_ref()
    else:
        raise ValueError(f"Unknown kind: {kind}")
    original = scm.head_ref()
    with pytest.raises(exception, match=target):
        scm.revert_commit(target)
    assert scm.head_ref() == original
    assert not git(git_repo, "status", "--porcelain")


@pytest.mark.parametrize("kind", ["empty", "already-reverted"])
def test_git_revert_nothing_to_revert(git_repo, commit_file, kind):
    scm = GitSCM(str(git_repo))
    target = commit_file(git_repo, "broken")
    if kind == "empty":
        git(git_repo, "commit", "--allow-empty", "-m", "Empty")
        target = scm.head_ref()
    elif kind == "already-reverted":
        scm.revert_commit(target)
    else:
        raise ValueError(f"Unknown kind: {kind}")
    original = scm.head_ref()
    with pytest.raises(SCMException):
        scm.revert_commit(target)
    scm.reset_to_commit(original)
    scm.revert_commit(commit_file(git_repo, "next"))


def test_git_revert_conflict(git_repo, commit_file):
    scm = GitSCM(str(git_repo))
    commit_file(git_repo, "base\n")
    target = commit_file(git_repo, "broken\n")
    original = commit_file(git_repo, "subsequent change\n")
    with pytest.raises(PatchConflict) as raised:
        scm.revert_commit(target)
    assert "backout-test" in raised.value.conflicts
    scm.reset_to_commit(original)
    scm.revert_commit(original)
