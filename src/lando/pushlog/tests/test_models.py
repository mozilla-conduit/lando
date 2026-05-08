import pytest
from django.db.utils import IntegrityError

from lando.pushlog.models import Commit, File, Tag


@pytest.mark.django_db()
def test__pushlog__models__Commit(make_repo, make_commit):
    repo = make_repo(1)
    commit = make_commit(repo, 1)

    commit.add_files(["file-1"])
    commit.add_files(["file-2"])

    commit.save()

    retrieved_commit = Commit.objects.get(repo=repo, hash=commit.hash)

    assert commit.hash in repr(commit)
    commit_str = str(commit)
    assert commit.repo.name in commit_str
    assert commit.hash in commit_str
    assert retrieved_commit.id == commit.id
    assert len(retrieved_commit.files) == 2


@pytest.mark.django_db()
def test__pushlog__models__Commit__from_scm_commit(
    make_repo, make_scm_commit, assert_same_commit_data
):
    repo = make_repo(1)
    scm_commit1 = make_scm_commit(1)
    scm_commit2 = make_scm_commit(2)
    commit1 = Commit.from_scm_commit(repo, scm_commit1)
    commit2 = Commit.from_scm_commit(repo, scm_commit2)

    commits_count = Commit.objects.filter(repo=repo).count()
    files_count = File.objects.filter(repo=repo).count()

    for commit, scm_commit in [(commit1, scm_commit1), (commit2, scm_commit2)]:
        assert not commit.id, "New commit {commit} was prematurely saved to the DB"
        assert_same_commit_data(commit, scm_commit)

    assert commit1.hash in commit2.parents

    # Nothing written to the DB yet.
    assert Commit.objects.filter(repo=repo).count() == commits_count
    assert File.objects.filter(repo=repo).count() == files_count

    commit1.save()
    commit2.save()

    # Now they have been written!
    assert Commit.objects.filter(repo=repo).count() == commits_count + 2
    assert File.objects.filter(repo=repo).count() == files_count + len(
        set(scm_commit1.files + scm_commit2.files)
    )

    for commit, scm_commit in [(commit1, scm_commit1), (commit2, scm_commit2)]:
        assert (
            commit.id
        ), "New commit {commit} doesn't have an ID after being saved to the DB"
        assert_same_commit_data(commit, scm_commit)


@pytest.mark.skip("Can't do this until we have a fully populated commit list")
@pytest.mark.django_db()
def test__pushlog__models__Commit__missing_parent(make_repo, make_scm_commit):
    repo = make_repo(1)
    scm_commit2 = make_scm_commit(2)  # expect parent to be commit1
    commit2 = Commit.from_scm_commit(repo, scm_commit2)

    with pytest.raises(Commit.DoesNotExist):
        commit2.save()


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

    for file in files:
        file_str = str(file)
        assert file.name in repr(files)
        assert file.name in file_str
        assert repo.name in file_str

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
    repo = make_repo(1)
    make_commit(repo, 1)

    with pytest.raises(
        IntegrityError,
        match=r"duplicate key.*pushlog_commit_repo_id",
    ):
        make_commit(repo, 1)


@pytest.mark.django_db()
def test__pushlog__models__File_unique(make_repo, make_file):
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

    tag_str = str(tag1)
    assert tag1.name in tag_str
    assert tag1.repo.name in tag_str
    assert tag1.commit.hash in tag_str

    assert tag1.name in repr(tag1)

    assert retrieved_tags.count() == 2
    assert rtag1.id == tag1.id


@pytest.mark.django_db()
def test__pushlog__models__Tag_unique(make_repo, make_commit, make_tag):
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

    push11_str = str(push11)
    assert f"Push {push11.push_id}" in push11_str
    assert push11.repo.name in push11_str

    push11_repr = repr(push11)
    assert f"(push_id={push11.push_id}" in push11_repr
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
