import subprocess

from django.core.management.base import BaseCommand

from lando.settings import LINT_PATHS, PRETTIER_PATHS


class Command(BaseCommand):
    help = "Run ruff, djlint, and prettier on the codebase"

    def handle(self, *args, **options):
        for lint_path in LINT_PATHS:
            subprocess.call(
                (
                    "ruff",
                    "check",
                    "--fix",
                    lint_path,
                )
            )

        subprocess.call(("ruff", "format") + LINT_PATHS)

        subprocess.call(("djlint", *LINT_PATHS, "--reformat"))

        subprocess.call(("prettier", "--write", *PRETTIER_PATHS))
