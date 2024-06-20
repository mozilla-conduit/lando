from django.contrib.auth.models import User
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from lando.main.models.profile import Profile


class LandoOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    """An extended OIDC auth backend that manipulates the user profile."""

    @staticmethod
    def _update_user_profile_permissions(user_profile, claims):
        # Store user info in the user profile.
        user_profile.userinfo = claims
        user_profile.save()

        # Update user permissions.
        user_profile.update_permissions()

    @staticmethod
    def _get_or_create_user_profile(user):
        # Check if there is an existing user profile, create it if not.
        try:
            user_profile = user.profile
        except User.profile.RelatedObjectDoesNotExist:
            user_profile = Profile(user=user)
            user_profile.save()
        return user_profile

    def post_auth_hook(self, user, claims):
        """Perform user profile related tasks upon login."""
        user_profile = self._get_or_create_user_profile(user)
        self._update_user_profile_permissions(user_profile, claims)

    def create_user(self, claims):
        user = super().create_user(claims)
        self.post_auth_hook(user, claims)
        return user

    def update_user(self, user, claims):
        self.post_auth_hook(user, claims)
        return super().update_user(user, claims)
