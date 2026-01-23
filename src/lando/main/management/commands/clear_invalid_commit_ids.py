from argparse import ArgumentParser

from django.core.management.base import BaseCommand
from django.db import transaction

from lando.main.models.revision import RevisionLandingJob
from lando.main.scm.git import GitSCM


class Command(BaseCommand):
    help = "One-time command to clear invalid `commit_id` values from `RevisionLandingJob`."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "repo_path",
            help="Path to the Git repository to check commits against.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be cleared without making changes.",
        )

    def handle(self, repo_path: str, dry_run: bool, **options):
        git_scm = GitSCM(path=repo_path)

        jobs_with_commit_id = RevisionLandingJob.objects.filter(
            commit_id__isnull=False
        ).exclude(commit_id="")

        total = jobs_with_commit_id.count()
        self.stdout.write(
            f"Checking {total} RevisionLandingJob objects with commit_id values..."
        )

        invalid_records = []
        for job in jobs_with_commit_id:
            if not git_scm.commit_exists(job.commit_id):
                self.stdout.write(
                    f"  RevisionLandingJob {job.id}: commit {job.commit_id} does not exist"
                )
                invalid_records.append(job)

        invalid_count = len(invalid_records)
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {invalid_count} invalid commit_id values would be cleared."
                )
            )
            return

        with transaction.atomic():
            for job in invalid_records:
                job.commit_id = None
                job.save(update_fields=["commit_id"])

        self.stdout.write(
            self.style.SUCCESS(f"Cleared {invalid_count} invalid commit_id values.")
        )
