import subprocess
from datetime import datetime, timedelta

import pytest

from lando.main.scm import PatchConflict
from lando.main.scm.exceptions import CommitNotFound, SCMException
from lando.main.scm.git import GitSCM

DAY = timedelta(hours=24)
CENTURY = timedelta(days=100 * 365)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def commit_file(create_git_commit_sha):
    def _commit_file(repo, content):
        return create_git_commit_sha(
            repo,
            message="Bug 123 - Break startup",
            name="backout-test",
            content=content,
        )

    return _commit_file


def test_git_revert(git_repo, commit_file):
    scm = GitSCM(str(git_repo))
    base_tree = git(git_repo, "rev-parse", "HEAD^{tree}")
    target = commit_file(git_repo, "broken")
    with scm.for_push("hackbot@mozilla.tld"):
        scm.revert_commit(target.upper(), CENTURY)
    assert git(git_repo, "rev-parse", "HEAD^{tree}") == base_tree
    assert git(git_repo, "show", "-s", "--format=%B") == (
        f'Revert "Bug 123 - Break startup"\n\nThis reverts commit {target}.'
    )
    assert git(git_repo, "show", "-s", "--format=%ae") == "pytest@lando.example.net"
    assert git(git_repo, "show", "-s", "--format=%ce") == "hackbot@mozilla.tld"
    assert scm.describe_commit().reverted_commit_hashes() == [target]
    assert not git(git_repo, "status", "--porcelain")


@pytest.mark.parametrize(
    "setup,target_args,exception",
    [
        ([], ["rev-parse", "0" * 40], CommitNotFound),
        ([], ["rev-parse", "HEAD:backout-test"], CommitNotFound),
        (
            [["tag", "-a", "annotated", "-m", "Annotated tag"]],
            ["rev-parse", "annotated"],
            CommitNotFound,
        ),
        (
            [
                ["checkout", "-b", "unlanded"],
                ["commit", "--allow-empty", "-m", "Unlanded"],
                ["checkout", "main"],
            ],
            ["rev-parse", "unlanded"],
            ValueError,
        ),
        ([], ["rev-list", "--max-parents=0", "HEAD"], ValueError),
        (
            [["merge", "--no-ff", "dev", "-m", "Merge dev"]],
            ["rev-parse", "HEAD"],
            ValueError,
        ),
    ],
)
def test_git_revert_rejects_invalid_targets(
    git_repo, commit_file, setup, target_args, exception
):
    scm = GitSCM(str(git_repo))
    commit_file(git_repo, "broken")
    for command in setup:
        git(git_repo, *command)
    target = git(git_repo, *target_args)
    original = scm.head_ref()
    with pytest.raises(exception, match=target):
        scm.revert_commit(target, CENTURY)
    assert scm.head_ref() == original
    assert not git(git_repo, "status", "--porcelain")


@pytest.mark.parametrize(
    "setup,target_rev",
    [
        ([["commit", "--allow-empty", "-m", "Empty"]], "HEAD"),
        ([["revert", "--no-edit", "HEAD"]], "HEAD~1"),
    ],
)
def test_git_revert_nothing_to_revert(git_repo, commit_file, setup, target_rev):
    scm = GitSCM(str(git_repo))
    commit_file(git_repo, "broken")
    for command in setup:
        git(git_repo, *command)
    target = git(git_repo, "rev-parse", target_rev)
    original = scm.head_ref()
    with pytest.raises(SCMException):
        scm.revert_commit(target, CENTURY)
    scm.reset_to_commit(original)
    next_target = commit_file(git_repo, "next")
    scm.revert_commit(next_target, CENTURY)
    assert scm.describe_commit().reverted_commit_hashes() == [next_target]
    assert git(git_repo, "rev-parse", "HEAD^{tree}") == git(
        git_repo, "rev-parse", f"{original}^{{tree}}"
    )


def test_git_revert_conflict(git_repo, commit_file):
    scm = GitSCM(str(git_repo))
    commit_file(git_repo, "base\n")
    target = commit_file(git_repo, "broken\n")
    original = commit_file(git_repo, "subsequent change\n")
    with pytest.raises(PatchConflict) as raised:
        scm.revert_commit(target, CENTURY)
    assert "backout-test" in raised.value.conflicts
    scm.reset_to_commit(original)
    scm.revert_commit(original, CENTURY)
    assert scm.describe_commit().reverted_commit_hashes() == [original]
    assert (git_repo / "backout-test").read_text() == "broken\n"


def test_git_revert_older_than_max_age(git_repo, commit_file):
    target = commit_file(git_repo, "broken")
    with pytest.raises(ValueError, match="more than 24 hours ago"):
        GitSCM(str(git_repo)).revert_commit(target, DAY)


@pytest.mark.parametrize(
    "commit_age,max_age",
    [
        (timedelta(0), DAY),
        (timedelta(hours=48), timedelta(hours=72)),
    ],
)
def test_git_revert_within_max_age(
    git_repo, commit_file, monkeypatch, commit_age, max_age
):
    monkeypatch.setenv("GIT_COMMITTER_DATE", (datetime.now() - commit_age).isoformat())
    scm = GitSCM(str(git_repo))
    target = commit_file(git_repo, "broken")
    scm.revert_commit(target, max_age)
    assert scm.describe_commit().reverted_commit_hashes() == [target]
