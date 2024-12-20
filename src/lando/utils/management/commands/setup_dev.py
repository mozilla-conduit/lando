from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from lando.environments import Environment
from lando.main.models import Repo, Worker
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG


class Command(BaseCommand):
    help = "Generate required database records used in dev."

    def setup_workers(self):
        """Ensure a git and an hg worker exist on the local environment."""
        # Set up two workers, one for each SCM.
        workers = {
            SCM_TYPE_GIT: None,
            SCM_TYPE_HG: None,
        }

        for worker_scm in workers:
            try:
                worker = Worker.objects.get(name=worker_scm)
                self.stdout.write(f"Found {worker} worker.")
            except Worker.DoesNotExist:
                # Set the name of the worker to match the SCM.
                worker = Worker(name=worker_scm, scm=worker_scm)
                worker.save()
                self.stdout.write(f"Created {worker} worker.")
            finally:
                workers[worker_scm] = worker

        for repo in Repo.objects.all():
            # Associate all repos with applicable worker.
            self.stdout.write(
                f"Adding {repo} ({repo.scm_type}) to {workers[repo.scm_type]}."
            )
            workers[repo.scm_type].applicable_repos.add(repo)
        self.stdout.write(
            self.style.SUCCESS(
                'Workers initialized ("hg" and "git"). '
                "To start one, run `lando start_landing_worker <name>`.",
            )
        )

    def setup_users(self):
        """Ensure there is an administrator account on the local system."""
        # In case someone is trying to run this manually for whatever reason on a
        # different environment, raise an exception so an admin user with a weak
        # password is not accidentally created.
        if settings.ENVIRONMENT != Environment.local:
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
        self.stdout.write(
            self.style.SUCCESS(
                "Superuser created with the following username and password: "
                '"admin", "password".'
            )
        )

    def handle(self, *args, **options):
        if settings.ENVIRONMENT != Environment.local:
            raise CommandError("This script can only be run on a local environment.")
        call_command("migrate")
        call_command("create_environment_repos", Environment.local.value)
        self.setup_workers()
        self.setup_users()
        self.stdout.write(
            self.style.SUCCESS("Finished setting up local Lando environment.")
        )
