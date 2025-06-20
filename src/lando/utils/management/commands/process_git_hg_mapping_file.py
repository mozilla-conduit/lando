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

    def _prepare_rows(self):
        # See bug 1888169.
        # Download original git2hg mapping file and extract it.
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

        # Download second (remainder) backup file.
        url = (
            "https://gist.github.com/zzzeid/8442141e8b12dfdede1f325a42b7d0f7/"
            "raw/4672ef4820b401a3157f28be277b70398cb057a6/git2hg_2.csv"
        )
        content = requests.get(url).text
        self.rows += list(csv.DictReader(StringIO(content)))

    def handle(self, *args, **options):
        self._prepare_rows()
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
