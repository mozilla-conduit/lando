from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from lando.main.models import Repo, Worker


class Command(BaseCommand):
    help = "Generate required database records used in dev."

    def setup_workers(self):
        """Ensure a git and an hg worker exist on the local environment."""
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

    def setup_users(self):
        """Ensure there is an administrator account on the local system."""
        # In case someone is trying to run this manually for whatever reason on a
        # different environment, raise an exception so an admin user with a weak
        # password is not accidentally created.
        if settings.ENVIRONMENT != "local":
            raise CommandError("This method can not be triggered on this environment.")

        try:
            user = User.objects.get(username="admin")
            self.stdout.write(f"Admin user ({user}) found, resetting settings.")
        except User.DoesNotExist:
            user = User.objects.create_user("admin", password="password")
            self.stdout.write(f"Admin user ({user}) created.")
        user.is_superuser = True
        user.is_staff = True
        user.save()

    def handle(self, *args, **options):
        if settings.ENVIRONMENT != "local":
            raise CommandError("This script can only be run on a local environment.")
        self.setup_workers()
        self.setup_users()
        self.stdout.write("Finished.")
