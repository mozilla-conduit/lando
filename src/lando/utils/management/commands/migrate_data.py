import argparse

from django.core.management import BaseCommand, CommandError, CommandParser

from lando.main.models import SCM_ALLOW_DIRECT_PUSH
from lando.main.models.commit_map import CommitMap
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

    def migrate_2_bug2050335_update_commit_map_thunderbird_desktop(
        self, ask_confirm: bool = True
    ):
        """
        Update CommitMap entries for `thunderbird`, to use `thunderbird-desktop`
        instead.

        This is to match the implicit use of the git_repo_name for lookups.
        """
        tbird_commit_maps = CommitMap.objects.filter(git_repo_name="thunderbird")
        if not tbird_commit_maps:
            self.stdout.write("No CommitMaps entries for `thunderbird`.")
            raise SystemExit()

        self._get_confirmation(
            ask_confirm,
            f"Updating {len(tbird_commit_maps)} CommitMaps to use `thunderbird-desktop` instead of `thunderbird`.",
            "",
        )

        tbird_commit_maps = CommitMap.objects.raw("""
            UPDATE main_commitmap
            SET git_repo_name='thunderbird-desktop'
            WHERE git_repo_name='thunderbird'
            """)

        self.stdout.write("done.")
