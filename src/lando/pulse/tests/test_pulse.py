from collections.abc import Callable

import pytest
from kombu import Connection, Consumer, Exchange, Producer, Queue

from lando.pulse.pulse import PulseNotifier

# We need to import dependencies of the fixtures we use, even if we don't use those
# directly.
from lando.pushlog.tests.conftest import make_commit, make_hash, make_push, make_repo

# We need some local usage of those imported fixtures to satisfy the linters.
# This is it.
__all__ = ["make_commit", "make_hash", "make_push", "make_repo"]


@pytest.fixture()
def kombu_connection():
    return Connection("memory://")


@pytest.fixture()
def kombu_exchange():
    return Exchange("test_exchange", type="direct")


@pytest.fixture()
def make_kombu_queue(kombu_connection, kombu_exchange):
    def queue_factory(routing_key="routing_key"):
        queue = Queue("test-queue", kombu_exchange, routing_key=routing_key)
        queue.maybe_bind(kombu_connection)
        queue.declare()
        return queue

    return queue_factory


@pytest.fixture
def kombu_queue_maker(
    kombu_connection: Connection,
    kombu_exchange: Exchange,
    make_kombu_queue: Callable,
):
    """Generator yielding first a Producer, then a list of received messages.

    This fixture returns a generator that first yields a Producer, then a list of
    received messages.

    Once the generator has been obtained, it MUST be used to publish some messages
    prior to requesting the list of received messages. Otherwise, the call will hold for
    short amount of time, and the returned list will be empty.

    """

    def build_queue(routing_key: str):

        # Producer
        producer = Producer(
            channel=kombu_connection.channel(),
            exchange=kombu_exchange,
            routing_key=routing_key,
        )
        queue = make_kombu_queue(routing_key="routing_key")

        yield producer

        # Consumer
        messages = []

        def consumer_callback(body, message):
            messages.append((body, message))
            message.ack()

        with Consumer(
            kombu_connection,
            queues=queue,
            callbacks=[consumer_callback],
        ):
            try:
                kombu_connection.drain_events(timeout=2)
            except TimeoutError:
                pass

        yield messages

    return build_queue


@pytest.mark.django_db
def test__PulseNotifier(
    make_repo: Callable,
    make_commit: Callable,
    make_push: Callable,
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
    push = make_push(repo=repo, commits=[commit])

    notifier.notify_push(push)

    messages = next(queue)

    assert messages
    message = messages[0][0]["payload"]
    assert message["push_id"] == push.push_id
    assert message["type"] == "push"
    assert message["repo_url"] == push.repo_url
    assert repo.default_branch in message["branches"]
    assert message["branches"][repo.default_branch] == commit.hash
    assert not message["tags"]
    assert message["user"] == push.user
    # XXX: https://bugzilla.mozilla.org/show_bug.cgi?id=1957549
    # assert message['push_json_url'] == push.push_json_url
    # assert message['push_full_json_url'] == push.push_full_json_url
