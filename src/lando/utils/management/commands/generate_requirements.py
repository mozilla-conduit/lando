import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate requirements.txt file to be used in local and remote environments"

    def add_arguments(self, parser):  # noqa: ANN001
        """Add options to pass to piptools."""
        parser.add_argument(
            "--upgrade",
            action="store_true",
            help="Upgrade all packages to latest versions",
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

        command.append("pyproject.toml")

        self.stdout.write(f"Running command {' '.join(command)}.")

        subprocess.run(command)
