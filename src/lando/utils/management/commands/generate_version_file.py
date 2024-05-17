from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Explicitly generate the 'version.py' file."

    def handle(self, *args, **options):
        from setuptools_scm import get_version

        get_version(write_to="src/lando/version.py")
