from django.core.management.base import BaseCommand

from lando.main.models import Repo, Worker


class Command(BaseCommand):
    help = "Generate required database records used in dev."

    def handle(self, *args, **options):
        # Set up two workers, one for each SCM.
        workers = {
            Repo.HG: None,
            Repo.GIT: None,
        }

        for worker_scm in workers:
            try:
                worker = Worker.objects.get(name=worker_scm)
                self.stdout.write(f"Found {worker} worker.")
            except Worker.DoesNotExist:
                # Set the name of the worker to match the SCM.
                worker = Worker(name=worker_scm)
                worker.save()
                self.stdout.write(f"Created {worker} worker.")
            finally:
                workers[worker_scm] = worker

        for repo in Repo.objects.all():
            # Associate all repos with applicable worker.
            self.stdout.write(f"Adding {repo} ({repo.scm}) to {workers[repo.scm]}.")
            workers[repo.scm].applicable_repos.add(repo)

        self.stdout.write("Finished.")
