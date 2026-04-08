import argparse
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from lando.main.models.profile import Profile
from lando.utils.phabricator import PhabricatorClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Back-fill `phabricator_phid` for profiles that have an API key but no PHID."
    name = "backfill_phids"

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually make changes. Without this flag, only logs what would be done.",
        )

    def handle(self, *args, **options):
        execute = options["execute"]

        profiles = Profile.objects.filter(
            phabricator_phid__isnull=True,
        ).exclude(
            encrypted_phabricator_api_key=b"",
        )

        self.stdout.write(
            f"Found {profiles.count()} profiles with an API key but no PHID."
        )

        for profile in profiles:
            api_key = profile.phabricator_api_key
            if not api_key:
                logger.debug(
                    "Profile %s has an empty API key after decryption, skipping.",
                    profile.pk,
                )
                continue

            phab = PhabricatorClient(settings.PHABRICATOR_URL, api_key)
            whoami = phab.verify_api_token()

            if not whoami:
                self.stdout.write(
                    self.style.WARNING(
                        f"Profile {profile.pk} (user={profile.user}): "
                        f"API key is invalid, skipping."
                    )
                )
                continue

            phid = whoami["phid"]
            username = whoami.get("userName", "unknown")

            if not execute:
                self.stdout.write(
                    f"[DRY RUN] Profile {profile.pk} (user={profile.user}): "
                    f"would set PHID to `{phid}` (`{username}`)."
                )
                continue

            existing = (
                Profile.objects.filter(
                    phabricator_phid=phid,
                )
                .exclude(pk=profile.pk)
                .first()
            )

            if existing:
                self.stdout.write(
                    self.style.WARNING(
                        f"Profile {profile.pk} (user={profile.user}): "
                        f"PHID `{phid}` (`{username}`) is already claimed by "
                        f"profile {existing.pk} (user={existing.user}), skipping."
                    )
                )
                continue

            profile.phabricator_phid = phid
            profile.save(update_fields=["phabricator_phid"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Profile {profile.pk} (user={profile.user}): "
                    f"set PHID to `{phid}` (`{username}`)."
                )
            )
