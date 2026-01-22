import argparse
import csv
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

import requests
from django.core.management.base import BaseCommand
from django.db.utils import IntegrityError

from lando.main.models import CommitMap


class Command(BaseCommand):
    help = "Download and process the git to hg mapping file"
    file_paths = None
    rows = []

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--url",
            default="",
            help="URL for additional csv file",
        )

    def _prepare_rows(self, **options):
        if not options["url"]:
            filename = "git2hg.csv"
            url = f"https://archive.mozilla.org/pub/vcs-archive/{filename}.zip"
            zip_file_path = Path("/tmp") / f"{filename}.zip"
            file_path = Path("/tmp") / filename

            with zip_file_path.open("wb") as f:
                self.stdout.write(f"Downloading {url}...")
                f.write(requests.get(url).content)

            with ZipFile(zip_file_path, "r") as f:
                self.stdout.write(f"Extracting {zip_file_path}...")
                f.extractall(Path("/tmp"))

            with file_path.open("r") as f:
                self.rows += list(csv.DictReader(f))
        else:
            # Download second (remainder) backup file.
            url = options["url"]
            content = requests.get(url).text
            self.rows += list(csv.DictReader(StringIO(content)))

    def handle(self, *args, **options):
        self._prepare_rows(**options)
        count = 0
        skipped_count = 0

        for row in self.rows:
            try:
                CommitMap.objects.create(
                    git_hash=row["git"],
                    hg_hash=row["hg"],
                    git_repo_name="firefox",
                )
            except IntegrityError:
                self.stdout.write(f"Skipped {row}.")
                skipped_count += 1
            else:
                count += 1

        self.stdout.write(f"Created {count} records.")
        self.stdout.write(f"Skipped {skipped_count} records.")
