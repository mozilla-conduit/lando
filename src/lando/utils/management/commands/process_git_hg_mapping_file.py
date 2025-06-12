import csv
from pathlib import Path
from zipfile import ZipFile

import requests
from django.core.management.base import BaseCommand
from django.db.utils import IntegrityError

from lando.main.models import CommitMap


class Command(BaseCommand):
    help = "Download and process the git to hg mapping file" ""

    def handle(self, *args, **options):
        # See bug 1888169.
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
            rows = list(csv.DictReader(f))

        count = 0
        for row in rows:
            try:
                CommitMap.objects.create(
                    git_hash=row["git"],
                    hg_hash=row["hg"],
                    git_repo_name="firefox",
                )
            except IntegrityError:
                pass
            else:
                count += 1

        self.stdout.write(f"Created {count} records.")
