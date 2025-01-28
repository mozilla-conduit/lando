import pytest
from django.db.utils import IntegrityError

from lando.pushlog.models import Commit, File, Tag


@pytest.mark.django_db()
def test__pushlog__models__Commit(make_repo, make_commit, make_file):
    # Model.objects.create() creates _and saves_ the object
    repo = make_repo(1)
    commit = make_commit(repo, 1)

    file1 = make_file(repo, 1)
    file2 = make_file(repo, 2)

    commit.files.add(file1)
    commit.files.add(file2)
    commit.save()

    retrieved_commit = Commit.objects.get(hash=commit.hash)

    assert commit.hash in repr(commit)
    assert retrieved_commit.id == commit.id
    assert retrieved_commit.files.count() == 2


@pytest.mark.django_db()
def test__pushlog__models__Commit__add_files(make_repo, make_commit):
    repo = make_repo(1)

    commit1 = make_commit(repo, 1)
    commit1.add_files(["file-1"])
    commit1.add_files(["file-2"])
    commit1.save()

    commit2 = make_commit(repo, 2)
    commit2.add_files(["file-1"])
    commit2.add_files(["file-3"])
    commit2.save()

    files = File.objects.filter(repo=repo)

    assert files.count() == 3
    # We use repr to also test File.__repr__ here.
    assert "file-1" in repr(files)
    assert "file-2" in repr(files)
    assert "file-3" in repr(files)

    files = File.objects.filter(commit=commit1)
    assert files.count() == 2
    assert "file-1" in repr(files)
    assert "file-2" in repr(files)

    files = File.objects.filter(commit=commit2)
    assert files.count() == 2
    assert "file-1" in repr(files)
    assert "file-3" in repr(files)


@pytest.mark.django_db()
def test__pushlog__models__Commit_unique(make_repo, make_commit):
    # Model.objects.create() creates _and saves_ the object
    repo = make_repo(1)
    make_commit(repo, 1)

    with pytest.raises(
        IntegrityError,
        match=r"duplicate key.*pushlog_commit_repo_id",
    ):
        make_commit(repo, 1)


@pytest.mark.django_db()
def test__pushlog__models__File_unique(make_repo, make_file):
    # Model.objects.create() creates _and saves_ the object
    repo = make_repo(1)
    make_file(repo, 1)

    with pytest.raises(
        IntegrityError,
        match=r"duplicate key.*pushlog_file_repo_id",
    ):
        make_file(repo, 1)


@pytest.mark.django_db()
def test__pushlog__models__Tag(make_repo, make_commit, make_tag):
    repo = make_repo(1)
    commit = make_commit(repo, 1)

    tag1 = make_tag(repo, 1, commit)
    make_tag(repo, 2, commit)

    retrieved_tags = Tag.objects.filter(commit=commit)
    rtag1 = retrieved_tags.get(name=tag1.name)

    assert tag1.name in repr(tag1)

    assert retrieved_tags.count() == 2
    assert rtag1.id == tag1.id


@pytest.mark.django_db()
def test__pushlog__models__Tag_unique(make_repo, make_commit, make_tag):
    # Model.objects.create() creates _and saves_ the object
    repo = make_repo(1)
    commit = make_commit(repo, 1)
    make_tag(repo, 1, commit)

    with pytest.raises(
        IntegrityError,
        match=r"duplicate key.*pushlog_tag_repo_id",
    ):
        make_tag(repo, 1, commit)


@pytest.mark.django_db()
def test__pushlog__models__Push(make_repo, make_commit, make_push):
    repo1 = make_repo(1)
    repo2 = make_repo(2)

    commit11 = make_commit(repo1, 1)
    commit12 = make_commit(repo1, 2)
    push11 = make_push(repo1, [commit11, commit12])

    commit21 = make_commit(repo2, 1)
    commit22 = make_commit(repo2, 2)
    push21 = make_push(repo2, [commit21, commit22])

    commit13 = make_commit(repo1, 3)
    commit14 = make_commit(repo1, 4)
    push12 = make_push(repo1, [commit13, commit14])

    push11_repr = repr(push11)
    assert f"({push11.push_id}" in push11_repr
    assert str(repo1) in push11_repr

    assert push11.repo_url == repo1.url
    assert push11.branch == repo1.default_branch

    assert push21.repo_url == repo2.url
    assert push21.branch == repo2.default_branch

    # Ensure that the push_id are scoped by repo.
    assert push11.push_id == 1
    assert (
        push21.push_id == 1
    ), "first push_id on second repository is not a strict incrementation"
    assert (
        push12.push_id == 2
    ), "second push_id on first repository is not a strict incrementation"

    push12.save()
    assert (
        push12.push_id == 2
    ), "second push_id on first repository has changed on re-save"
