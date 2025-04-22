import unittest.mock as mock

import pytest
from django.db.utils import IntegrityError

from lando.pushlog.models import Commit, Push, Tag
from lando.pushlog.pushlog import PushLog, PushLogForRepo


@pytest.mark.django_db()
def test__pushlog__PushLog(
    make_repo, make_scm_commit, make_tag, assert_same_commit_data
):
    repo = make_repo(1)
    user = "user@moz.test"

    push_count_before = Push.objects.count()
    commit_count_before = Commit.objects.count()
    tag_count_before = Tag.objects.count()

    with PushLogForRepo(repo, user) as pushlog:
        scm_commit1 = make_scm_commit(1)
        scm_commit2 = make_scm_commit(2)
        scm_commit3 = make_scm_commit(3)

        commit1 = pushlog.add_commit(scm_commit1)
        commit2 = pushlog.add_commit(scm_commit2)
        commit3 = pushlog.add_commit(scm_commit3)

        tag = pushlog.add_tag("test-tag", scm_commit2)

        pushlog.confirm()

    pushlog_string = repr(pushlog)
    assert repr(repo) in pushlog_string
    assert user in pushlog_string
    assert commit1.hash in pushlog_string
    assert commit2.hash in pushlog_string
    assert commit3.hash in pushlog_string

    # Check the commits
    assert Commit.objects.count() == commit_count_before + 3

    for commit, scm_commit in [
        (commit1, scm_commit1),
        (commit2, scm_commit2),
        (commit3, scm_commit3),
    ]:
        assert_same_commit_data(commit, scm_commit)

    # Check the tag
    assert Tag.objects.count() == tag_count_before + 1

    db_tag = Tag.objects.filter(repo=repo, name=tag.name).get()

    # Check the tag
    assert db_tag
    assert db_tag.name == tag.name
    assert db_tag.commit == commit2

    # Check the push
    assert Push.objects.count() == push_count_before + 1

    push = Push.objects.filter(repo=repo, commits__in=[commit1]).get()
    push_tag = Push.objects.filter(repo=repo, tags__in=[tag]).get()

    assert push.push_id == push_tag.push_id

    assert push.commits.count() == 3
    assert commit1 in push.commits.all()
    assert commit2 in push.commits.all()
    assert commit3 in push.commits.all()

    assert push.tags.count() == 1
    assert tag in push.tags.all()


@pytest.mark.django_db()
def test__pushlog__PushLog_no_commit_on_exception(make_repo, make_scm_commit):
    repo = make_repo(1)

    push_count_before = Push.objects.count()
    commit_count_before = Commit.objects.count()

    try:
        with PushLogForRepo(repo, "user@moz.test") as pushlog:
            scm_commit1 = make_scm_commit(1)
            scm_commit2 = make_scm_commit(2)
            scm_commit3 = make_scm_commit(3)

            pushlog.add_commit(scm_commit1)
            pushlog.add_commit(scm_commit2)
            pushlog.add_commit(scm_commit3)

            pushlog.confirm()

            raise Exception()

    except Exception:
        pass

    assert Push.objects.count() == push_count_before
    assert Commit.objects.count() == commit_count_before


@pytest.mark.django_db()
def test__pushlog__PushLog_no_commit_on_unconfirmed(make_repo, make_scm_commit, caplog):
    repo = make_repo(1)

    push_count_before = Push.objects.count()
    commit_count_before = Commit.objects.count()

    with PushLogForRepo(repo, "user@moz.test") as pushlog:
        scm_commit1 = make_scm_commit(1)
        scm_commit2 = make_scm_commit(2)
        scm_commit3 = make_scm_commit(3)

        pushlog.add_commit(scm_commit1)
        pushlog.add_commit(scm_commit2)
        pushlog.add_commit(scm_commit3)

        # No call to pushlog.confirm()

    assert Push.objects.count() == push_count_before
    assert Commit.objects.count() == commit_count_before

    assert "wasn't confirmed" in caplog.text
    assert scm_commit1.hash in caplog.text
    assert scm_commit2.hash in caplog.text
    assert scm_commit3.hash in caplog.text


@pytest.mark.django_db()
def test__pushlog__PushLog_useful_log_on_error(
    monkeypatch, make_repo, make_scm_commit, caplog
):
    repo = make_repo(1)
    message = "Oh noes! The Push failed to be recorded!"

    scm_commit1 = make_scm_commit(1)
    scm_commit2 = make_scm_commit(1)

    with pytest.raises(IntegrityError):
        with PushLogForRepo(repo, "user@moz.test") as pushlog:
            mock_record_push = mock.MagicMock()
            mock_record_push.side_effect = IntegrityError(message)
            monkeypatch.setattr(pushlog, "record_push", mock_record_push)

            pushlog.add_commit(scm_commit1)
            pushlog.add_commit(scm_commit2)

            pushlog.confirm()

    assert message in caplog.text
    assert scm_commit1.hash in caplog.text
    assert scm_commit2.hash in caplog.text


@pytest.mark.django_db()
def test__pushlog__PushLog_no_double_record(make_repo, make_scm_commit):
    repo = make_repo(1)

    scm_commit = make_scm_commit(1)

    pushlog = PushLog(repo, "user@moz.test")
    pushlog.add_commit(scm_commit)
    pushlog.confirm()

    pushlog.record_push()

    with pytest.raises(RuntimeError):
        pushlog.record_push()


@pytest.mark.django_db()
def test__pushlog__PushLog__no_deadlock(make_repo, make_scm_commit):
    repo1 = make_repo(1)
    push_count_before1 = Push.objects.filter(repo=repo1).count()
    commit_count_before1 = Commit.objects.filter(repo=repo1).count()

    repo2 = make_repo(2)
    push_count_before2 = Push.objects.filter(repo=repo2).count()
    commit_count_before2 = Commit.objects.filter(repo=repo2).count()

    with PushLogForRepo(repo1, "user1@moz.test") as pushlog1:
        with PushLogForRepo(repo2, "user2@moz.test") as pushlog2:
            scm_commit11 = make_scm_commit(1)
            pushlog1.add_commit(scm_commit11)

            scm_commit21 = make_scm_commit(1)
            pushlog2.add_commit(scm_commit21)

            # Purposefully not in reverse order.
            pushlog1.confirm()
            pushlog2.confirm()

    assert Push.objects.filter(repo=repo1).count() == push_count_before1 + 1
    assert Commit.objects.filter(repo=repo1).count() == commit_count_before1 + 1

    assert Push.objects.filter(repo=repo2).count() == push_count_before2 + 1
    assert Commit.objects.filter(repo=repo2).count() == commit_count_before2 + 1


@pytest.mark.skip()
@pytest.mark.django_db()
def test__pushlog__PushLog_tag_to_non_existent_commit(make_repo, make_scm_commit):
    """Ensure that tags to commit not yet present in the DB create the commit."""
    repo = make_repo(1)
    user = "user@moz.test"

    with PushLogForRepo(repo, user) as pushlog:
        scm_commit2 = make_scm_commit(2)

        tag = pushlog.add_tag("test-tag-to-non-existent-commit", scm_commit2)

        pushlog.confirm()

    pushlog_string = repr(pushlog)
    assert repr(repo) in pushlog_string
    assert user in pushlog_string

    # Check the commit was created in the DB
    commit2 = Commit.objects.get(repo=repo, hash=scm_commit2.hash)
    assert commit2

    db_tag = Tag.objects.filter(repo=repo, name=tag.name).get()

    # Check the tag
    assert db_tag.name == tag.name
    assert db_tag.commit == commit2

    push = Push.objects.filter(tags__in=[tag]).get()

    assert push.commits.count() == 0
    assert push.tags.count() == 1
    assert tag in push.tags.all()
