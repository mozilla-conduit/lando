from django.core.management.base import BaseCommand
from setuptools_scm import get_version


class Command(BaseCommand):
    help = "Explicitly generate the 'version.py' file."

    def handle(self, *args, **options):
        get_version(write_to="src/lando/version.py")
