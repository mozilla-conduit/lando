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


@pytest.mark.django_db
def test__PulseNotifier(
    kombu_connection,
    kombu_exchange,
    make_kombu_queue,
    make_repo: Callable,
    make_commit: Callable,
    make_push: Callable,
):
    routing_key = "routing_key"

    # Producer.
    producer = Producer(
        channel=kombu_connection.channel(),
        exchange=kombu_exchange,
        routing_key=routing_key,
    )
    queue = make_kombu_queue(routing_key="routing_key")
    notifier = PulseNotifier(producer)

    # Test push.
    repo = make_repo(1)
    commit = make_commit(repo=repo, seqno=1)
    push = make_push(repo=repo, commits=[commit])

    notifier.notify_push(push)

    # Test consumer.
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

    assert messages
