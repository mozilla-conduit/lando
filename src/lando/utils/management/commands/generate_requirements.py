import argparse
import os
import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate requirements.txt file to be used in local and remote environments"

    def add_arguments(self, parser: argparse.ArgumentParser):
        """Add options to pass to piptools."""
        parser.add_argument(
            "--upgrade",
            action="store_true",
            help="Upgrade all packages to latest versions",
        )
        parser.add_argument(
            "--cooldown",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Whether to apply a cooldown an upgrades",
        )

    def handle(self, *args, **options):
        """Run piptools compile with relevant arguments."""
        command = [
            "python",
            "-m",
            "piptools",
            "compile",
            "--generate-hashes",
            "--allow-unsafe",
            "--extra=code-quality,testing",
            "--all-build-deps",
            "--output-file=requirements.txt",
        ]

        if options["upgrade"]:
            command.append("--upgrade")

        if options["cooldown"]:
            command.append("--pip-args=--uploaded-prior-to=P7D")

        command.append("pyproject.toml")

        env = os.environ.copy()
        # Tell setuptools_scm to ignore git complaints about ownership of /code in
        # container [0].
        # [0] https://github.com/pypa/setuptools-scm/pull/1235
        env["SETUPTOOLS_SCM_IGNORE_DUBIOUS_OWNER"] = "true"
        self.stdout.write(f"Running command {' '.join(command)}.")

        subprocess.run(command, env=env)
