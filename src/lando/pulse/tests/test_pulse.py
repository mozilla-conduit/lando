from collections.abc import Callable

import pytest
from kombu import Connection, Consumer, Exchange, Producer, Queue, log as kombu_log

from lando.pulse.pulse import PulseNotifier

# We need to import dependencies of the fixtures we use, even if we don't use those
# directly.
from lando.pushlog.tests.conftest import make_commit, make_hash, make_push, make_repo

# We need some local usage of those imported fixtures to satisfy the linters.
# This is it.
__all__ = ["make_commit", "make_hash", "make_push", "make_repo"]


@pytest.mark.django_db
def test__PulseNotifier(
    make_repo: Callable,
    make_commit: Callable,
    make_push: Callable,
):
    kombu_log.setup_logging(loglevel="DEBUG")

    connection = Connection("memory://")
    exchange = Exchange("test_exchange", type="direct")
    routing_key = "test_key"
    queue = Queue("test_queue", exchange, routing_key=routing_key)
    queue.maybe_bind(connection)
    queue.declare()

    # Producer.
    producer = Producer(
        channel=connection.channel(), exchange=exchange, routing_key=routing_key
    )
    print(producer)

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

    with Consumer(connection, queues=queue, callbacks=[consumer_callback]) as consumer:
        breakpoint()
        try:
            connection.drain_events(timeout=2)
        except TimeoutError:
            pass

    print(messages)
    assert messages
