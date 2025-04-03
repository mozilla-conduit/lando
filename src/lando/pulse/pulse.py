import logging

import kombu
from django.conf import settings

from lando.pushlog.models import Push

logger = logging.getLogger(__name__)


class PulseNotifier:
    producer: kombu.Producer

    def __init__(self, producer: kombu.Producer | None = None) -> None:
        if not producer:
            producer = self._make_producer()

        self.producer = producer

    @classmethod
    def _make_producer(cls) -> kombu.Producer:
        if settings.PULSE_HOST.startswith("memory"):
            message = (
                "PULSE_HOST set to a `memory` location. "
                + "This should not be the case in non-local deployments. "
                + str(settings.PULSE_HOST)
            )
            if settings.ENVIRONMENT.is_remote:
                # XXX: we should verify this much earlier on
                raise RuntimeError(message)
            logger.warning(message, extra={"PULSE_HOST": settings.PULSE_HOST})

        connection = kombu.Connection(
            hostname=settings.PULSE_HOST,
            port=settings.PULSE_PORT,
            userid=settings.PULSE_USER,
            password=settings.PULSE_PASSWORD,
            connect_timeout=100,
            ssl=settings.PULSE_SSL,
        )
        connection.connect()

        ex = kombu.Exchange(settings.PULSE_EXCHANGE, type="direct")
        queue = kombu.Queue(
            name=settings.PULSE_QUEUE,
            exchange=settings.PULSE_EXCHANGE,
            routing_key=settings.PULSE_ROUTING_KEY,
            durable=True,
            exclusive=False,
            auto_delete=False,
        )
        queue(connection).declare()

        producer = connection.Producer(
            exchange=ex, routing_key=settings.PULSE_ROUTING_KEY, serializer="json"
        )
        return producer

    def notify_push(self, push: Push):
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
