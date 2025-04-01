import argparse

from django.core.management.base import BaseCommand, CommandError, CommandParser

from lando.main.models.repo import Repo
from lando.pushlog.models import Push


class Command(BaseCommand):
    title = "View the pushlog for a given repository"
    name = "view_pushlog"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("-r", "--repo", required=True)
        parser.add_argument("-l", "--limit", type=int, default=0)
        parser.add_argument(
            "-c", "--commits", default=True, action=argparse.BooleanOptionalAction
        )

    def handle(self, *args, **options):
        repo_name = options["repo"]
        with_commits = options["commits"]
        limit = options["limit"]
        try:
            repo = Repo.objects.get(name=repo_name)
        except Repo.DoesNotExist:
            raise CommandError(f"Repository not found: {repo_name}")

        pushes = Push.objects.filter(repo=repo).order_by("-push_id")
        if limit:
            pushes = pushes[:limit]

        for push in pushes:
            self.stdout.write(push)
            if with_commits:
                for commit in push.commits.order_by("-datetime"):
                    self.stdout.write(f"  {commit}")
