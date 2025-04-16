import argparse

from django.core.management.base import BaseCommand, CommandError, CommandParser

from lando.main.models.repo import Repo
from lando.pulse.pulse import PulseNotifier
from lando.pushlog.models.push import Push


class Command(BaseCommand):
    help = """Send Pulse notification for selected Pushes.

        This should not be needed in normal operation, but could be useful when
        something went wrong and messages got lost.

        Caution should be taken when sending duplicate or out-of-order notifications.
        To prevent accidental use, those behaviours are guarded by CLI options to force them.
        """
    name = "pulse_notify"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("-r", "--repo", required=True)
        parser.add_argument("-p", "--push-id", type=int, default=0)
        parser.add_argument(
            "-R",
            "--force-renotify",
            default=False,
            action=argparse.BooleanOptionalAction,
        )
        parser.add_argument(
            "-O",
            "--force-out-of-order",
            default=False,
            action=argparse.BooleanOptionalAction,
        )

    def handle(self, *args, **options) -> None:
        repo_name = options["repo"]
        push_id = options["push_id"]
        force_renotify = options["force_renotify"]
        force_out_of_order = options["force_out_of_order"]

        return self._notify_push(repo_name, push_id, force_renotify, force_out_of_order)

    def _notify_push(
        self,
        repo_name: str,
        push_id: int,
        force_renotify: bool = False,
        force_out_of_order: bool = False,
    ):
        try:
            repo = Repo.objects.get(name=repo_name)
        except Repo.DoesNotExist:
            raise CommandError(f"Repository not found: {repo_name}")

        first_push = None
        try:
            first_push = Push.objects.filter(repo=repo, notified=False).first()
        except Push.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(f"No un-notified push for {repo_name}")
            )

        push = None
        if push_id:
            try:
                push = Push.objects.get(repo=repo, push_id=push_id)
            except Push.DoesNotExist:
                raise CommandError(f"Push {push_id} not found for {repo_name}")

            if first_push and first_push.push_id < push_id and not force_out_of_order:
                raise CommandError(
                    f"Push {push} is not the first un-notified push for {repo_name} (use --force-out-of-order to force, at your own risks)"
                )

        if push and push.notified and not force_renotify:
            raise CommandError(
                f"Push {push} has already been notified (use --force-renotify to force, at your own risks)"
            )

        push = push or first_push
        if not push:
            self.stdout.write("Nothing to do")
            return

        self.stdout.write(f"Notifying for {push} ...")

        notifier = PulseNotifier()
        try:
            notifier.notify_push(push)
        except Exception as exc:
            raise CommandError(f"Failed to notify push {push}: {exc}") from exc
