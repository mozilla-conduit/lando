from io import StringIO
from typing import Callable

import kombu
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_pulse_notify_no_repo():
    with pytest.raises(CommandError, match="required: -r"):
        call_command("pulse_notify")


@pytest.mark.django_db
def test_pulse_notify_no_push(
    make_commit: Callable, make_push: Callable, make_repo: Callable
):
    repo = make_repo(1)
    commit = make_commit(repo, 1)
    push = make_push(repo, [commit])
    push.notified = True
    push.save()

    out = StringIO()
    opts = {
        "repo": repo.name,
    }
    call_command("pulse_notify", stdout=out, **opts)

    assert "Nothing to do" in out.getvalue()


@pytest.mark.django_db
def test_pulse_notify_already_notified(
    make_commit: Callable, make_push: Callable, make_repo: Callable
):
    repo = make_repo(1)

    commit1 = make_commit(repo, 1)
    push1 = make_push(repo, [commit1])
    push1.notified = True
    push1.save()

    commit2 = make_commit(repo, 2)
    push2 = make_push(repo, [commit2])
    push2.save()

    opts = {
        "repo": repo.name,
        "push_id": 1,
    }
    with pytest.raises(CommandError, match="already been notified"):
        call_command("pulse_notify", **opts)


@pytest.mark.django_db
def test_pulse_notify_out_of_order(
    make_commit: Callable, make_push: Callable, make_repo: Callable
):
    repo = make_repo(1)

    commit1 = make_commit(repo, 1)
    push1 = make_push(repo, [commit1])
    push1.notified = True
    push1.save()

    commit2 = make_commit(repo, 2)
    push2 = make_push(repo, [commit2])
    push2.save()

    commit3 = make_commit(repo, 3)
    push3 = make_push(repo, [commit3])
    push3.save()

    opts = {
        "repo": repo.name,
        "push_id": 3,
    }
    with pytest.raises(CommandError, match="not the first"):
        call_command("pulse_notify", **opts)


@pytest.fixture
def mock_notifier_producer(monkeypatch):
    def set_notifier_producer(producer: kombu.Producer):
        def _make(cls) -> kombu.Producer:
            return producer

        monkeypatch.setattr("lando.pulse.pulse.PulseNotifier._make_producer", _make)

    return set_notifier_producer


@pytest.mark.django_db
def test_pulse_notify(
    kombu_queue_maker: Callable,
    make_commit: Callable,
    make_push: Callable,
    make_repo: Callable,
    mock_notifier_producer: Callable,
):
    repo = make_repo(1)

    commit = make_commit(repo, 1)
    push = make_push(repo, [commit])

    push.save()

    queue = kombu_queue_maker("pulse_notify")
    producer = next(queue)
    mock_notifier_producer(producer)

    out = StringIO()
    opts = {
        "repo": repo.name,
    }
    call_command("pulse_notify", stdout=out, **opts)

    user_message = out.getvalue()
    assert "Notifying" in user_message
    assert str(push) in user_message

    messages = next(queue)
    assert len(messages) == 1
    message_dict = messages[0][0]
    assert message_dict["payload"]["push_id"] == push.push_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "push_id,force_flag", [(1, "force_renotify"), (2, None), (3, "force_out_of_order")]
)
def test_pulse_notify_push_id_force(
    kombu_queue_maker: Callable,
    make_commit: Callable,
    make_push: Callable,
    make_repo: Callable,
    mock_notifier_producer: Callable,
    push_id: int,
    force_flag: str | None,
):
    """Create an arbitrary number of pushes, and test all notifications (incl. forced)."""
    repo = make_repo(1)

    for commit_id in range(push_id):  # create one fake commit per push
        commit = make_commit(repo, commit_id)
        push = make_push(repo, [commit])

        if commit_id == 0:
            push.notified = True

        push.save()

    queue = kombu_queue_maker("pulse_notify")
    producer = next(queue)
    mock_notifier_producer(producer)

    out = StringIO()
    opts = {
        "repo": repo.name,
        "push_id": push_id,
    }
    if force_flag:
        opts[force_flag] = True
    call_command("pulse_notify", stdout=out, **opts)

    user_message = out.getvalue()
    assert "Notifying" in user_message
    assert str(push) in user_message

    messages = next(queue)
    assert len(messages) == 1
    message_dict = messages[0][0]
    assert message_dict["payload"]["push_id"] == push.push_id
