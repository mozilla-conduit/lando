from mozilla_django_oidc.auth import OIDCAuthenticationBackend


class LandoOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    """An extended OIDC auth backend that manipulates the user profile."""

    def get_userinfo(self, *args, **kwargs):
        self.userinfo = super().get_userinfo(*args, **kwargs)
        return self.userinfo

    def update_user(self, user, claims):
        user.profile.userinfo = self.userinfo
        user.profile.save()
        return super().update_user(user, claims)
