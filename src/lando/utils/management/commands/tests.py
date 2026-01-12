import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

ROOT_DIR = settings.BASE_DIR.parent.parent


class Command(BaseCommand):
    help = "Run pytest from project directory"

    def add_arguments(self, parser):  # noqa: ANN001
        parser.add_argument(
            "--exitfirst",
            "-x",
            action="store_true",
            help="Exit instantly on first error or failed test",
        )

        parser.add_argument(
            "paths", nargs="*", type=str, help="Files or directories to pass to pytest"
        )

        parser.add_argument(
            "-k", type=str, help="Only run tests which match the given substring."
        )

        parser.add_argument(
            "--pdb",
            action="store_true",
            help="Start the interactive Python debugger on errors",
        )

        parser.add_argument(
            "-n",
            type=str,
            default="auto",
            help="Number of workers for pytest-xdist (default: auto)",
        )

    def handle(self, *args, **options):
        command = ["pytest"]

        if options["n"]:
            command.append("-n")
            command.append(options["n"])

        if options["k"]:
            command.append("-k")
            command.append(options["k"])

        if options["exitfirst"]:
            command.append("-x")

        if options["paths"]:
            command += options["paths"]

        if options["pdb"]:
            command.append("--pdb")

        env = os.environ.copy()
        env["DJANGO_SETTINGS_MODULE"] = "lando.test_settings"
        result = subprocess.run(command, cwd=ROOT_DIR, env=env)
        if result.returncode:
            raise CommandError(f"Pytest exited with exit code {result.returncode}")
