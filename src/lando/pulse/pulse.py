import logging

import kombu
from django.conf import settings

from lando.pushlog.models import Push

logger = logging.getLogger(__name__)


class PulseNotifier:
    """Class to generate and send Pulse notification based on Push objects."""

    producer: kombu.Producer

    def __init__(self, producer: kombu.Producer | None = None) -> None:
        self.producer = producer or self._make_producer()

    @classmethod
    def _make_producer(cls) -> kombu.Producer:
        connection = kombu.Connection(
            hostname=settings.PULSE_HOST,
            port=settings.PULSE_PORT,
            userid=settings.PULSE_USERID,
            password=settings.PULSE_PASSWORD,
            connect_timeout=100,
            ssl=settings.PULSE_SSL,
        )
        connection.connect()

        ex = kombu.Exchange(settings.PULSE_EXCHANGE, type="topic")

        producer = connection.Producer(
            exchange=ex, routing_key=settings.PULSE_ROUTING_KEY, serializer="json"
        )
        return producer

    def declare_exchange(self) -> kombu.Exchange:
        self.producer.exchange.declare()
        return self.producer.exchange

    def notify_push(self, push: Push):
        """Send a Pulse notification for the given Push."""
        message = self.pulse_message_for_push(push)

        # XXX: make a separate notification worker that loops around un-notified
        # Push entries.
        logger.info(f"Sending {message} ...")
        self.producer.publish(
            message,
            retry=True,
            retry_policy={
                "interval_start": 0,  # First retry immediately,
                "interval_step": 2,  # then increase by 2s for every retry.
                "interval_max": 30,  # but don't exceed 30s between retries.
                "max_retries": 30,  # give up after 30 tries.
            },
        )

        push.notified = True
        push.save()

    @classmethod
    def pulse_message_for_push(cls, push: Push) -> dict:
        """Generate Pulse notification payload for the given Push."""
        branches = {}
        if push.commits.count():
            commit = push.commits.latest()
            branches = {push.branch: commit.hash}

        # XXX: to be implemented in https://bugzilla.mozilla.org/show_bug.cgi?id=1957547
        tags = {}

        if not branches and not tags:
            logger.warning(
                f"Push {push.push_id} for repo {push.repo_url} does not contain either branches or tags"
            )

        message = {
            "payload": {
                "type": "push",
                "repo_url": push.repo_url,
                "branches": branches,
                "tags": tags,
                "time": push.datetime.strftime("%s"),
                "push_id": push.push_id,
                "user": push.user,
                # XXX: https://bugzilla.mozilla.org/show_bug.cgi?id=1957549
                "push_json_url": "FIXME",
                "push_full_json_url": "FIXME",
            }
        }
        return message
