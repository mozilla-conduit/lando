import subprocess

from django.core.management.base import BaseCommand, CommandError

from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)


class Command(BaseCommand):
    help = "Turn maintenance mode on or off"

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            help="Enter one of on, off",
        )

        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="Force the action regardless of database migration state",
        )

    def _turn_on_maintenance_mode(self):
        ConfigurationVariable.set(
            ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "1"
        )
        ConfigurationVariable.set(
            ConfigurationKey.LANDING_WORKER_PAUSED, VariableTypeChoices.BOOL, "1"
        )

    def _turn_off_maintenance_mode(self):
        ConfigurationVariable.set(
            ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "0"
        )
        ConfigurationVariable.set(
            ConfigurationKey.LANDING_WORKER_PAUSED, VariableTypeChoices.BOOL, "0"
        )

    def handle(self, *args, **options):
        action_mapping = {
            "on": self._turn_on_maintenance_mode,
            "off": self._turn_off_maintenance_mode,
        }
        action = options["action"]
        force = options["force"]
        if action not in action_mapping:
            raise CommandError(
                f"Action must be one of: {', '.join(action_mapping.keys())}. "
                f'"{action}" was provided.'
            )

        unapplied_migrations = (
            subprocess.run(["lando", "migrate", "--check", "--noinput"]).returncode != 0
        )

        if force or unapplied_migrations:
            action_mapping[action]()
