import subprocess
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Explicitly generate the 'version.py' file."

    def handle(self, *args, **options):
        subprocess.call([sys.executable, "code/generate_version_file.py"])
