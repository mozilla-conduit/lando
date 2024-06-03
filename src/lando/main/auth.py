from django.contrib.auth.models import User
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from lando.main.models.profile import Profile


class LandoOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def create_user(self, claims):
        return super().create_user(claims)

    def get_userinfo(self, *args, **kwargs):
        self.userinfo = super().get_userinfo(*args, **kwargs)
        return self.userinfo

    def update_user(self, user, claims):
        try:
            user_profile = user.profile
        except User.profile.RelatedObjectDoesNotExist:
            user_profile = Profile(user=user)
            user_profile.save()

        user_profile.userinfo = self.userinfo
        user_profile.save()
        user_profile.update_permissions()
        return super().update_user(user, claims)
