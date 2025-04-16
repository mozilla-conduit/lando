from django.core.management.base import BaseCommand, CommandError

from lando.pulse.pulse import PulseNotifier


class Command(BaseCommand):
    help = """Declare the Pulse exchange.

        Exchanges need to be declared before Queues can
        be bound to them to receive messages. Due to the nature of Pulse Lando is in charge
        of creating its own exchange, but Consumers manage their Queues.

        Lando will create the Exchange automatically when first sending a message, but this
        message would be lost as no Queues would be bound yet, and no Consumer would be able
        to listen for it.

        This commands allows to pre-declare the Exchange so the messaging chain can be
        prepared ahead of time."""
    name = "pulse_declare"

    def handle(self, *args, **options) -> None:
        notifier = PulseNotifier()
        try:
            exchange = notifier.declare_exchange()
        except Exception as exc:
            raise CommandError(f"Failed to declare exchange {exchange}: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Declared exchange {exchange.name} on {exchange._channel.connection}"
            )
        )
