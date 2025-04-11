from django.core.management.base import BaseCommand, CommandError

from lando.pulse.pulse import PulseNotifier


class Command(BaseCommand):
    help = "Declare the Pulse exchange"
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
