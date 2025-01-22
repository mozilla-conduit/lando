import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.db import models

from lando.main.models.base import BaseModel


class ApiToken(BaseModel):
    """API tokens for use with headless API."""

    # User who corresponds to this token.
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # 8-character prefix of the unsalted token for lookups.
    token_prefix = models.CharField(max_length=8, db_index=True)

    # Full hashed/salted token.
    token_hash = models.CharField(max_length=128, unique=True)

    # If the token is considered valid, or has been revoked.
    is_valid = models.BooleanField(default=True)

    @classmethod
    def create_token(cls, user: User) -> str:
        """Generate a token for the given user.

        Generate a secure token for the given `user` and store in the
        database. The token is returned in full for display.
        """
        # Generate the secure token.
        token = secrets.token_hex(nbytes=20)

        # Note the prefix for the index.
        token_prefix = token[:8]

        # Create the hashed/salted token.
        token_hash = make_password(token)

        cls.objects.create(user=user, token_prefix=token_prefix, token_hash=token_hash)

        return token

    @classmethod
    def verify_token(cls, token: str) -> User:
        """Verify a token and return the associated `User` if valid.

        Use the prefix of the given token to look up matching entries in the
        `ApiToken` table. Verify the full token against the stored hash
        """
        token_prefix = token[:8]
        token_prefix_matches = cls.objects.filter(token_prefix=token_prefix)

        for api_token_obj in token_prefix_matches:
            if not check_password(token, api_token_obj.token_hash):
                # The prefix matches, but the full token is incorrect.
                # Rare that this would happen, but not a failure.
                continue

            if not api_token_obj.is_valid:
                raise ValueError(f"Token {token} has been revoked.")

            return api_token_obj.user

        raise ValueError(f"Token {token} was not found.")
