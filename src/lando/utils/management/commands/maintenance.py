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

    def _pause_workers(self):
        """Pause all workers."""
        # We explicitely select the `is_paused` field, and defer the others.
        # This allows a new version of lando to Pause workers during an update, even
        # with pending migrations in the Worker model, that would otherwise result in
        # UndefinedColumn errors if trying to fetch all (expected) fields.
        workers = Worker.objects.raw("SELECT id, is_paused from main_worker")
        for worker in workers:
            worker.pause()
            self.stdout.write(f"Paused {worker}.")

    def _resume_workers(self):
        """Resume all workers."""
        workers = Worker.objects.all()
        for worker in workers:
            worker.resume()
            self.stdout.write(f"Resumed {worker}.")

    def _turn_on_maintenance_mode(self):
        """Put the web interface into maintenance mode."""
        ConfigurationVariable.set(
            ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "1"
        )
        self.stdout.write("Turned maintenance mode on for web interface.")

    def _turn_off_maintenance_mode(self):
        """Put the web interface back online."""
        ConfigurationVariable.set(
            ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "0"
        )
        self.stdout.write("Turned maintenance mode off for web interface.")

    def handle(self, *args, **options):
        ON = "on"
        OFF = "off"

        actions = (ON, OFF)
        action = options["action"]
        if action not in actions:
            raise CommandError(
                f"Action must be one of: {', '.join(actions)}. "
                f'"{action}" was provided.'
            )

        # If there are unapplied migrations, then both the web interface and the
        # workers need to be put in maintenance.
        unapplied_migrations = (
            subprocess.run(["lando", "migrate", "--check", "--noinput"]).returncode != 0
        )

        if action == ON:
            if unapplied_migrations:
                self.stdout.write("Found unapplied migrations.")
                self._turn_on_maintenance_mode()
            self._pause_workers()
            sys.exit()
        elif action == OFF:
            self._resume_workers()
            self._turn_off_maintenance_mode()
            sys.exit()
