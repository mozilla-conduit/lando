import logging
from argparse import ArgumentParser

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from lando.headless_api.models.tokens import ApiToken

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create an API token for a given user."

    def add_arguments(self, parser: ArgumentParser):
        parser.add_argument("email", help="Email address of user.")

    def handle(self, email: str, **options):
        """Create an API token for the specified user."""
        try:
            user = User.objects.get(email=email)
        except User.NotFoundError:
            raise CommandError(f"Could not find user with email {email}")

        try:
            token = ApiToken.create_token(user)
        except Exception as exc:
            raise CommandError("Error creating token.") from exc

        self.stdout.write(self.style.SUCCESS(f"Token created for {email}"))
        self.stdout.write(self.style.SUCCESS(f"Token: {token}"))
        self.stdout.write(
            self.style.NOTICE(
                "Once the user has received their token, they will need the\n"
                "`headless_api.add_automationjob` permission on their user profile."
            )
        )
