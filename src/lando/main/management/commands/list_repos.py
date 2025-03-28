from django.core.management.base import BaseCommand

from lando.main.models.repo import Repo


class Command(BaseCommand):
    help = "List available repositories"
    name = "list_repos"

    def handle(self, *args, **options):
        for repo in Repo.objects.all():
            self.stdout.write(f"{repo.name}: {repo.url} ({repo.scm_type})")
