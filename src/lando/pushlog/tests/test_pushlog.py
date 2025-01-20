import pytest

from lando.pushlog.pushlog import PushLogForRepo


@pytest.mark.django_db()
def test__pushlog__PushLog(make_repo):
    repo = make_repo(1)

    with PushLogForRepo(repo) as pushlog:
        print(pushlog)
        # r = pushlog.add_revision(...)
        # r.add_files( ...)


@pytest.mark.django_db()
def test__pushlog__PushLog_no_commit_on_exception(make_repo):
    repo = make_repo(1)

    try:
        with PushLogForRepo(repo) as pushlog:
            print(pushlog)
            raise Exception()

    except Exception:
        pass

    assert False  # XXX test that pushlog not updated


@pytest.mark.django_db()
def test__pushlog__PushLog__no_deadlock(make_repo):
    repo1 = make_repo(1)
    repo2 = make_repo(2)

    with PushLogForRepo(repo1) as pushlog1:
        with PushLogForRepo(repo2) as pushlog2:
            print(pushlog1)
            print(pushlog2)
            # r = pushlog.add_revision(...)
            # r.add_files( ...)
