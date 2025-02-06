import logging

from kombu import Producer

from lando.pushlog.models import Push

logger = logging.getLogger(__name__)

class PulseNotifier:
    producer: Producer

    def __init__(self, producer: Producer) -> None:
        self.producer = producer

    def notify_push(self, push: Push):
        message = {
            "type": "push",
            "payload": {
                "pushid": push.push_id,
            },
        }

        # XXX: make a separate notification worker that loops around un-notified
        # Push entries.
        logger.warning(f"Sending {message} ...")
        self.producer.publish(
            message,
            retry=True,
        )

        # push.notified = True:with expression as target:
