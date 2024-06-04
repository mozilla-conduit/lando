from django.contrib.auth.models import User
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from lando.main.models.profile import Profile


class LandoOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    """An extended OIDC auth backend that manipulates the user profile."""

    def get_userinfo(self, *args, **kwargs):
        # Store fetched userinfo on this instance.
        self.userinfo = super().get_userinfo(*args, **kwargs)
        return self.userinfo

    def update_user(self, user, claims):
        # Check if there is an existing user profile, create it if not.
        try:
            user_profile = user.profile
        except User.profile.RelatedObjectDoesNotExist:
            user_profile = Profile(user=user)
            user_profile.save()

        # Store user info in the user profile.
        user_profile.userinfo = self.userinfo
        user_profile.save()

        # Update user permissions.
        user_profile.update_permissions()

        return super().update_user(user, claims)
