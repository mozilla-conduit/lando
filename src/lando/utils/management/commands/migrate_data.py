import argparse

from django.core.management import BaseCommand, CommandError, CommandParser

from lando.main.models import SCM_ALLOW_DIRECT_PUSH
from lando.main.models.repo import Repo


class Command(BaseCommand):
    help = """This stub commands allows to run data migrations.

    It should be fleshed out as part of bug 2013991.
    """
    # TODO: record already-applied migrations.

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "-l", "--list", default=False, action=argparse.BooleanOptionalAction
        )
        parser.add_argument(
            "-y",
            "--yes",
            default=False,
            help="Don't ask for confirmation",
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument("migration", help="Migration to apply", nargs="?")

    def handle(self, *args, **options):
        ask_confirm = not options.get("yes", False)

        if options.get("list"):
            self.stdout.write("Available data migrations:\n")
            for migration in [
                method.removeprefix("migrate_")
                for method in dir(self)
                if method.startswith("migrate_")
            ]:
                self.stdout.write(f"* {migration}")
            raise SystemExit()

        if not (migration := options.get("migration")):
            raise CommandError("No migration specified")

        method_name = f"migrate_{migration}"

        if not (migration_method := getattr(self, method_name)):
            raise CommandError("Migration method not found: {method_name}")

        migration_method(ask_confirm)

    def _get_confirmation(self, ask_confirm: bool, prompt: str, details: str):
        """Show a confirmation prompt with details.

        If ask_confirm is set, details are printed prior to requesting confirmation.

        Otherwise, let the caller show the details as it proceeds.
        """
        self.stdout.write(prompt, ending="")
        if ask_confirm:
            self.stdout.write(f"{details}. Confirm [yN]? ", ending="")
            if input().lower() != "y":
                raise CommandError("User interruption")

            self.stdout.write("Progress: ", ending="")

    #
    # MIGRATION METHODS
    #

    def migrate_1_bug1971103_add_firefox_required_automation_permissions(
        self, ask_confirm: bool = True
    ):
        """
        Explicitly set the  `required_automation_permission` for all Firefox repos.

        This is to match the currectly implicit authorisation for Firefox sheriffs.
        """
        fx_repos = Repo.objects.filter(
            name__startswith="firefox-", required_automation_permission=""
        )
        if not fx_repos:
            self.stdout.write(
                "No firefox-% repo found with NULL required_automation_permission."
            )
            raise SystemExit()

        fx_repo_names = ", ".join(repo.name for repo in fx_repos)
        self._get_confirmation(
            ask_confirm, "Updating required_automation_permission for: ", fx_repo_names
        )

        for repo in fx_repos:
            if not repo.required_automation_permission:
                repo.required_automation_permission = SCM_ALLOW_DIRECT_PUSH
                repo.save()
                self.stdout.write(f"{repo.name} ", ending="")

        self.stdout.write("done.")

    def migrate_2_bug1709608_enable_prevent_empty_binary_hook(
        self, ask_confirm: bool = True
    ):
        """
        Enable the `PreventEmptyBinaryCheck` hook for all Phabricator repos.

        See bug 1709608: a Phabricator diff whose `creationMethod` is `commit`
        can land binary files as zero bytes. The hook defends every landing
        path, but it only fires when enabled on a repo.
        """
        hook = Repo.HooksChoices.PreventEmptyBinaryCheck.value
        phab_repos = Repo.objects.filter(is_phabricator_repo=True).exclude(
            hooks__contains=[hook]
        )
        if not phab_repos:
            self.stdout.write(f"No Phabricator repo found without the {hook} hook.")
            raise SystemExit()

        repo_names = ", ".join(repo.name for repo in phab_repos)
        self._get_confirmation(ask_confirm, f"Enabling {hook} hook for: ", repo_names)

        for repo in phab_repos:
            repo.hooks = (repo.hooks or []) + [hook]
            repo.save()
            self.stdout.write(f"{repo.name} ", ending="")

        self.stdout.write("done.")
