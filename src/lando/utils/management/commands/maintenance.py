import subprocess
import sys

from django.core.management.base import BaseCommand, CommandError

from lando.main.models import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
    Worker,
)


class Command(BaseCommand):
    help = "Turn maintenance mode on or off"

    def add_arguments(self, parser):  # noqa: ANN001
        parser.add_argument(
            "action",
            help="Enter one of on, off",
        )

        parser.add_argument(
            "-c",
            "--check-migrations",
            action="store_true",
            default=False,
            help="Do not turn on maintenance if there are no unapplied migrations",
        )

    def _turn_on_maintenance_mode(self):
        ConfigurationVariable.set(
            ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "1"
        )
        workers = Worker.objects.all()
        for worker in workers:
            worker.is_paused = True
            worker.save()

    def _turn_off_maintenance_mode(self):
        ConfigurationVariable.set(
            ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "0"
        )
        workers = Worker.objects.all()
        for worker in workers:
            worker.is_paused = False
            worker.save()

    def handle(self, *args, **options):
        action_mapping = {
            "on": self._turn_on_maintenance_mode,
            "off": self._turn_off_maintenance_mode,
        }
        action = options["action"]
        check = options["check_migrations"]
        if action not in action_mapping:
            raise CommandError(
                f"Action must be one of: {', '.join(action_mapping.keys())}. "
                f'"{action}" was provided.'
            )

        if not check:
            action_mapping[action]()
            self.stdout.write(f"Turned maintenance mode {action}.")
            sys.exit()

        unapplied_migrations = (
            subprocess.run(["lando", "migrate", "--check", "--noinput"]).returncode != 0
        )
        if unapplied_migrations:
            self.stdout.write("Found unapplied migrations.")
            self.stdout.write(f"Turning maintenance mode {action}.")
            action_mapping[action]()
        else:
            self.stdout.write("No unapplied migrations found, not action taken.")
