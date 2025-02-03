import unittest.mock as mock

import pytest
from django.db.utils import IntegrityError

from lando.pushlog.models import Commit, Push
from lando.pushlog.pushlog import PushLogForRepo


@pytest.mark.django_db()
def test__pushlog__PushLog(make_repo, make_scm_commit, assert_same_commit_data):
    repo = make_repo(1)
    user = "user@moz.test"

    push_count_before = Push.objects.count()
    commit_count_before = Commit.objects.count()

    with PushLogForRepo(repo, user) as pushlog:
        scm_commit1 = make_scm_commit(1)
        scm_commit2 = make_scm_commit(2)
        scm_commit3 = make_scm_commit(3)

        commit1 = pushlog.add_commit(scm_commit1)
        commit2 = pushlog.add_commit(scm_commit2)
        commit3 = pushlog.add_commit(scm_commit3)

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

    # Check the push
    assert Push.objects.count() == push_count_before + 1

    push = Push.objects.filter(commits__in=[commit1]).get()

    assert push.commits.count() == 3
    assert commit1 in push.commits.all()
    assert commit2 in push.commits.all()
    assert commit3 in push.commits.all()


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

            raise Exception()

    except Exception:
        pass

    assert Push.objects.count() == push_count_before
    assert Commit.objects.count() == commit_count_before


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

    assert message in caplog.text
    assert scm_commit1.hash in caplog.text
    assert scm_commit2.hash in caplog.text


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

    assert Push.objects.filter(repo=repo1).count() == push_count_before1 + 1
    assert Commit.objects.filter(repo=repo1).count() == commit_count_before1 + 1

    assert Push.objects.filter(repo=repo2).count() == push_count_before2 + 1
    assert Commit.objects.filter(repo=repo2).count() == commit_count_before2 + 1
