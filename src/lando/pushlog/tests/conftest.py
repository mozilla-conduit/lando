from datetime import datetime

import pytest

from lando.main.models import Repo
from lando.pushlog.models import Commit, File, Push, Tag


@pytest.fixture
def make_repo():
    def repo_factory(seqno: int) -> Repo:
        "Create a non-descript repository with a sequence number in the test DB."
        return Repo.objects.create(name=f"repo-{seqno}", scm_type="git")

    return repo_factory


@pytest.fixture
def make_hash():
    def hash_factory(seqno: int):
        return str(seqno).zfill(8) + "f" + 31 * "0"

    return hash_factory


@pytest.fixture
def make_commit(make_hash):
    def commit_factory(repo: Repo, seqno: int, message=None) -> Commit:
        "Create a non-descript commit with a sequence number in the test DB."
        if not message:
            message = f"Commit {seqno}"

        return Commit.objects.create(
            # Create a 40-character string, of which the first 8 bytes represent the seqno
            # in decimal representation.
            hash=make_hash(seqno),
            repo=repo,
            author=f"author-{seqno}",
            desc=message,
            date=datetime.now(),
        )

    return commit_factory


@pytest.fixture
def make_file():
    def file_factory(repo: Repo, seqno: int) -> File:
        "Create a non-descript file with a sequence number in the test DB."
        return File.objects.create(
            repo=repo,
            name=f"file-{seqno}",
        )

    return file_factory


@pytest.fixture
def make_tag():
    def tag_factory(repo: Repo, seqno: int, commit: Commit) -> Tag:
        "Create a non-descript tag with a sequence number in the test DB."
        return Tag.objects.create(
            repo=repo,
            name=f"tag-{seqno}",
            commit=commit,
        )

    return tag_factory


@pytest.fixture
def make_push():
    def push_factory(repo: Repo, commits: list[Commit]):
        "Create a non-descript push containing the associated commits in the test DB."
        push = Push.objects.create(repo=repo)
        for c in commits:
            push.commits.add(c)
        push.save()

        return push

    return push_factory
