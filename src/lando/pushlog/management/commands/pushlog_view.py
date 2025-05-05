import argparse

from django.core.management.base import BaseCommand, CommandError, CommandParser

from lando.main.models.repo import Repo
from lando.pushlog.models import Push


class Command(BaseCommand):
    title = "View the pushlog for a given repository"
    name = "pushlog_view"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("-l", "--limit", type=int, default=0)
        parser.add_argument("-p", "--push-id", type=int, default=0)
        parser.add_argument("-r", "--repo", required=True)
        parser.add_argument(
            "-c", "--with-commits", default=True, action=argparse.BooleanOptionalAction
        )
        parser.add_argument(
            "-t", "--with-tags", default=True, action=argparse.BooleanOptionalAction
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        push_id = options["push_id"]
        repo_name = options["repo"]
        with_commits = options["with_commits"]
        with_tags = options["with_tags"]
        try:
            repo = Repo.objects.get(name=repo_name)
        except Repo.DoesNotExist:
            raise CommandError(f"Repository not found: {repo_name}")

        if push_id > 0:
            pushes = Push.objects.filter(repo=repo, push_id=push_id)
        else:
            pushes = Push.objects.filter(repo=repo).order_by("-push_id")
            if limit:
                pushes = pushes[:limit]

        if not pushes:
            push_id_info = f" (push_id {push_id})" if push_id > 0 else ""
            raise CommandError(f"No push found for {repo_name}{push_id_info}")

        for push in pushes:
            self.stdout.write(f"{push} (notified: {push.notified})")
            if with_commits:
                for commit in push.commits.order_by("-datetime"):
                    self.stdout.write(f"  {commit}")
            if with_tags:
                for commit in push.tags.all():
                    self.stdout.write(f"  {commit}")
