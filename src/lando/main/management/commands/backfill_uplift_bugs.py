import argparse
import logging

from django.core.management.base import BaseCommand

from lando.api.legacy.revisions import get_bug_id_for_revision
from lando.main.models.uplift import UpliftAssessment
from lando.utils.phabricator import get_phabricator_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Back-fill `bug_id` on uplift assessments recorded before the field existed."
    name = "backfill_uplift_bugs"

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually make changes. Without this flag, only logs what would be done.",
        )

    def handle(self, *args, **options):
        execute = options["execute"]

        # The privileged key is used rather than each author's own, so a secure
        # revision still resolves and an author who has rotated or never set a
        # key does not leave their assessment ungrouped. Only the bug number is
        # read, and it does not widen who can see the assessment.
        phab = get_phabricator_client(privileged=True)

        assessments = UpliftAssessment.objects.filter(bug_id__isnull=True)

        self.stdout.write(f"Found {assessments.count()} assessments with no bug.")

        for assessment in assessments:
            revision_id = self.revision_to_resolve_from(assessment)

            if revision_id is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"Assessment {assessment.pk}: no revision to resolve a bug "
                        f"from, skipping."
                    )
                )
                continue

            bug_id = get_bug_id_for_revision(phab, revision_id)

            if bug_id is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"Assessment {assessment.pk}: D{revision_id} has no bug "
                        f"number, skipping."
                    )
                )
                continue

            if not execute:
                self.stdout.write(
                    f"[DRY RUN] Assessment {assessment.pk}: would set bug to "
                    f"{bug_id} (from D{revision_id})."
                )
                continue

            assessment.bug_id = bug_id
            assessment.save(update_fields=["bug_id"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Assessment {assessment.pk}: set bug to {bug_id} "
                    f"(from D{revision_id})."
                )
            )

    @staticmethod
    def revision_to_resolve_from(assessment: UpliftAssessment) -> int | None:
        """Return a Phabricator revision ID carrying this assessment's bug.

        Prefers a linked revision, falling back to the revisions an uplift was
        requested for. Returns `None` when the assessment reaches neither.
        """
        linked = assessment.revisions.exclude(revision_id=None).first()
        if linked:
            return linked.revision_id

        for submission in assessment.uplift_submission.all():
            for revision_id in submission.requested_revision_ids:
                return revision_id

        return None
