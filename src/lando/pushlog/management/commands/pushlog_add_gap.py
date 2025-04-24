from django.core.management.base import BaseCommand, CommandError, CommandParser

from lando.main.models.repo import Repo
from lando.pushlog.models import Push


class Command(BaseCommand):
    title = "Create a gap in the Pushlog IDs"
    name = "pushlog_add_gap"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("-r", "--repo", required=True)
        parser.add_argument("-p", "--next_push_id", type=int, default=0)

    def handle(self, *args, **options):
        repo_name = options["repo"]
        next_push_id = options["next_push_id"]

        try:
            repo = Repo.objects.get(name=repo_name)
        except Repo.DoesNotExist:
            raise CommandError(f"Repository not found: {repo_name}")

        pushes = Push.objects.filter(repo=repo, push_id__gte=next_push_id).order_by(
            "-push_id"
        )

        if pushes:
            push = pushes.first()
            raise CommandError(
                f"Pushes with ID>={next_push_id} already exist for {repo_name}: {push}"
            )

        stub_push_id = next_push_id - 1
        push = Push.objects.filter(repo=repo, push_id=stub_push_id)
        if push:
            self.stdout.write(
                self.style.NOTICE(
                    f"Push with ID {stub_push_id} already exists for {repo_name}; not doing anything"
                )
            )
            return

        push = Push.objects.create(repo=repo, user="pushlog_add_gap@lando-cli")
        # We need to override the push_id which is auto-generated on first save().
        push.push_id = stub_push_id
        push.save()
        self.stdout.write(f"Created Push with ID {stub_push_id} for {repo_name}")
