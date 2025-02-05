import kombu

from lando.pushlog.models import Push


class PulseNotifier:
    connection: kombu.Connection

    def __init__(self, connection: kombu.Connection) -> None:
        self.connection = connection

    def notify_push(self, push: Push):
        with self.connection.channel() as channel:
            producer = kombu.Producer(channel)

            message = {
                "type": "push",
                "payload": {
                    "pushid": push.pushid,
                },
            }

            # XXX: make a separate notification worker that loops around un-notified
            # Push entries
            producer.publish(
                message,
                retry=True,
                retry_policy={
                    "interval_start": 0,  # First retry immediately,
                    "interval_step": 2,  # then increase by 2s for every retry.
                    "interval_max": 30,  # but don't exceed 30s between retries.
                    "max_retries": 30,  # give up after 30 tries.
                },
            )
