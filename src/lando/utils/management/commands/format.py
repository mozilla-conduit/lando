import subprocess

from django.core.management.base import BaseCommand

LINT_PATHS = ("lando", "main", "utils", "api")


class Command(BaseCommand):
    help = "Run ruff and black on the codebase"

    def handle(self, *args, **options):
        for lint_path in LINT_PATHS:
            subprocess.call(
                ("ruff", "check", "--fix", "--target-version", "py39", lint_path)
            )

        subprocess.call(("black",) + LINT_PATHS)
