import subprocess

from django.core.management.base import BaseCommand

from lando.settings import LINT_PATHS, RUFF_TARGET_VERSION


class Command(BaseCommand):
    help = "Run ruff and black on the codebase"

    def handle(self, *args, **options):
        for lint_path in LINT_PATHS:
            subprocess.call(
                (
                    "ruff",
                    "check",
                    "--fix",
                    "--target-version",
                    RUFF_TARGET_VERSION,
                    lint_path,
                )
            )

        subprocess.call(("black",) + LINT_PATHS)
