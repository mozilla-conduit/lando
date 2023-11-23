from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test command"

    def add_arguments(self, parser):
        parser.add_argument("names", nargs="+")

    def handle(self, *args, **options):
        for name in options["names"]:
            self.stdout.write(self.style.SUCCESS(f"Hello {name}!"))
