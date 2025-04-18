from collections.abc import Callable

import pytest

from lando.pulse.pulse import PulseNotifier


@pytest.mark.django_db
def test__PulseNotifier(
    make_repo: Callable,
    make_commit: Callable,
    make_push: Callable,
    make_tag: Callable,
    kombu_queue_maker: Callable,
):
    routing_key = "routing_key"

    queue = kombu_queue_maker(routing_key)
    producer = next(queue)
    notifier = PulseNotifier(producer)

    # Test push.
    repo = make_repo(1)
    commit = make_commit(repo=repo, seqno=1)
    # An unrelated commit we don't want to see in the push
    make_commit(repo=repo, seqno=2)

    tag = make_tag(repo, 1, commit)
    tag_name = tag.name

    push = make_push(repo=repo, commits=[commit], tags=[tag])

    notifier.notify_push(push)

    messages = next(queue)

    assert messages
    message = messages[0][0]["payload"]
    assert message["push_id"] == push.push_id
    assert message["type"] == "push"
    assert message["repo_url"] == push.repo_url
    assert repo.default_branch in message["branches"]
    assert message["branches"][repo.default_branch] == commit.hash
    assert tag_name in message["tags"]
    assert message["tags"][tag_name] == commit.hash
    assert message["user"] == push.user
    # XXX: https://bugzilla.mozilla.org/show_bug.cgi?id=1957549
    # assert message['push_json_url'] == push.push_json_url
    # assert message['push_full_json_url'] == push.push_full_json_url
