from datetime import datetime

import pytest

from lando.main.models import Repo
from lando.main.scm import SCM_TYPE_GIT
from lando.main.scm.commit import Commit as SCMCommit
from lando.pushlog.models import Commit, File, Push, Tag


@pytest.fixture
def make_repo():
    def repo_factory(seqno: int) -> Repo:
        """Create a non-descript repository with a sequence number in the test DB."""
        return Repo.objects.create(
            name=f"repo-{seqno}",
            scm_type=SCM_TYPE_GIT,
            url=f"https://repo-{seqno}",
            default_branch=f"main-{seqno}",
        )

    return repo_factory


@pytest.fixture
def make_hash():
    def hash_factory(seqno: int):
        """Create a hash-like hex string, including the seqno in decimal representation."""
        return str(seqno).zfill(8) + "f" + 31 * "0"

    return hash_factory


@pytest.fixture
def make_commit(make_hash):
    def commit_factory(repo: Repo, seqno: int, message=None) -> Commit:
        """Create a non-descript commit with a sequence number in the test DB."""
        if not message:
            message = f"Commit {seqno}"

        return Commit.objects.create(
            hash=make_hash(seqno),
            repo=repo,
            author=f"author-{seqno}",
            desc=message,
            datetime=datetime.now(),
        )

    return commit_factory


@pytest.fixture
def make_file():
    def file_factory(repo: Repo, seqno: int) -> File:
        """Create a non-descript file with a sequence number in the test DB."""
        return File.objects.create(
            repo=repo,
            name=f"file-{seqno}",
        )

    return file_factory


@pytest.fixture
def make_tag():
    def tag_factory(repo: Repo, seqno: int, commit: Commit) -> Tag:
        """Create a non-descript tag with a sequence number in the test DB."""
        return Tag.objects.create(
            repo=repo,
            name=f"tag-{seqno}",
            commit=commit,
        )

    return tag_factory


@pytest.fixture
def make_push():
    def push_factory(repo: Repo, commits: list[Commit]):
        """Create a non-descript push containing the associated commits in the test DB."""
        push = Push.objects.create(repo=repo, user="Push-User")
        for c in commits:
            push.commits.add(c)
        push.save()

        return push

    return push_factory


@pytest.fixture
def make_scm_commit(make_hash):
    def scm_commit_factory(seqno: int):
        return SCMCommit(
            hash=make_hash(seqno),
            author=f"author-{seqno}",
            desc=f"""SCM Commit {seqno}

Another line""",
            datetime=datetime.now(),
            # The first commit doesn't have a parent.
            parents=[make_hash(seqno - 1)] if seqno > 1 else [],
            files=[f"/file-{s}" for s in range(seqno)],
        )

    return scm_commit_factory


@pytest.fixture
def assert_same_commit_data():
    def assertion(commit: Commit, scm_commit: SCMCommit):
        assert commit.hash == scm_commit.hash

        assert len(commit.parents) == len(scm_commit.parents)
        assert set(commit.parents) == set(scm_commit.parents)

        assert commit.author == scm_commit.author
        assert commit.datetime == scm_commit.datetime
        assert commit.desc == scm_commit.desc

        assert len(commit.files) == len(scm_commit.files)
        assert set(commit.files) == set(scm_commit.files)

    return assertion
