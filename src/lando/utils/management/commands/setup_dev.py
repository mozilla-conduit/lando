from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from lando.environments import Environment
from lando.headless_api.models.tokens import ApiToken
from lando.main.auth import CONDUIT_ADMIN_GROUP_NAME
from lando.main.models import Repo, Worker
from lando.main.models.worker import WorkerType
from lando.main.scm import SCMType


class Command(BaseCommand):
    help = "Generate required database records used in dev."

    @staticmethod
    def _raise_if_not_local():
        if settings.ENVIRONMENT != Environment.local:
            raise CommandError("This method can not be triggered on this environment.")

    def setup_workers(self):
        """Ensure a git and an hg worker exist on the local environment."""
        self._raise_if_not_local()

        # Set up workers for each SCM. Historically, the worker with no suffix is the landing worker.
        worker_scm_types = {
            SCMType.GIT: {
                WorkerType.LANDING: "",
                WorkerType.AUTOMATION: "-automation-worker",
                WorkerType.UPLIFT: "-uplift-worker",
            },
            SCMType.HG: {
                WorkerType.LANDING: "",
            },
        }

        workers = {}

        for worker_scm, worker_type in [
            (scm, type) for scm, types in worker_scm_types.items() for type in types
        ]:
            worker_name = f"{worker_scm}{worker_scm_types[worker_scm][worker_type]}"
            try:
                worker = Worker.objects.get(name=worker_name)
                self.stdout.write(f"Found {worker} worker.")
            except Worker.DoesNotExist:
                # Set the name of the worker to match the SCM.
                worker = Worker(name=worker_name, scm=worker_scm, type=worker_type)
                worker.save()
                self.stdout.write(f"Created {worker} worker.")
            finally:
                workers[worker_name] = worker

        for repo in Repo.objects.all():
            # Associate all repos with applicable worker.
            for worker in workers.values():
                if worker.scm != repo.scm_type:
                    continue
                if repo.worker_set.exists():
                    self.stdout.write(f"Adding {repo} ({repo.scm_type}) to {worker}.")
                    worker.applicable_repos.add(repo)
        self.stdout.write(
            self.style.SUCCESS(
                f"Workers initialized ({', '.join(list(workers))}). "
                "To start one, run `lando start_landing_worker <name>` or `lando start_automation_worker <name>`.",
            )
        )

    def setup_users(self):
        """Ensure there is an administrator account on the local system."""
        # In case someone is trying to run this manually for whatever reason on a
        # different environment, raise an exception so an admin user with a weak
        # password is not accidentally created.
        self._raise_if_not_local()

        try:
            user = User.objects.get(username="admin")
            self.stdout.write(f"Admin user ({user}) found, resetting settings.")
        except User.DoesNotExist:
            user = User.objects.create_user(
                "admin", password="password", email="test@example.org"
            )
            self.stdout.write(f"Admin user ({user}) created.")
        user.is_staff = True
        user.save()
        add_automationjob = Permission.objects.get(codename="add_automationjob")
        user.user_permissions.add(add_automationjob)
        Group.objects.get(name=CONDUIT_ADMIN_GROUP_NAME).user_set.add(user)
        token = "a" * 128

        ApiToken.objects.create(
            user=user,
            **ApiToken._get_token_parts(token),
        )

        self.stdout.write(self.style.SUCCESS(f"Token created for {user}"))
        self.stdout.write(self.style.SUCCESS(f"Token: {token}"))
        self.stdout.write(
            self.style.SUCCESS(
                "Superuser created with the following username and password: "
                '"admin", "password".'
            )
        )

    def setup_groups(self):
        self._raise_if_not_local()
        try:
            conduit_admin = Group.objects.get(name=CONDUIT_ADMIN_GROUP_NAME)
            self.stdout.write(f"({conduit_admin}) found.")
        except Group.DoesNotExist:
            conduit_admin = Group.objects.create(name=CONDUIT_ADMIN_GROUP_NAME)
            self.stdout.write(f"({conduit_admin}) created.")
        for permission in Permission.objects.all():
            conduit_admin.permissions.add(permission)

    def handle(self, *args, **options):
        self._raise_if_not_local()
        call_command("migrate")
        call_command("create_environment_repos", Environment.local.value)
        self.setup_workers()
        self.setup_groups()
        self.setup_users()
        self.stdout.write(
            self.style.SUCCESS("Finished setting up local Lando environment.")
        )
