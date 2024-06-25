from django.core.management.base import BaseCommand
from lando.main.models import Repo, Worker


class Command(BaseCommand):
    help = "Generate required database records used in dev."

    def handle(self, *args, **options):
        # Get or create repo.
        try:
            repo = Repo.objects.get(name="git-test-repo")
        except Repo.DoesNotExist:
            repo_url = "https://github.com/zzzeid/test-repo.git"
            repo = Repo(
                name="git-test-repo",
                url=repo_url,
                push_path=repo_url,
                pull_path=repo_url,
            )
            repo.save()

        # Get or create landing worker.
        try:
            worker = Worker.objects.get(name="landing-worker")
        except Worker.DoesNotExist:
            worker = Worker(
                name="landing-worker",
            )
            worker.save()

        # Add repo to worker.
        worker.applicable_repos.add(repo)
