from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Temporary no-op until the uplift worker command is fully implemented."

    def handle(self, *args, **options) -> None:
        """Intentionally left blank to avoid deployment issues during rollout."""
        self.stdout.write(
            "start_uplift_worker placeholder: command currently a no-op.",
        )
