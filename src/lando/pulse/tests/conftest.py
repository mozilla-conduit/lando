from typing import Callable

import pytest
from kombu import Connection, Consumer, Exchange, Producer, Queue


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
