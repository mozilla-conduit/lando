import functools
from typing import (
    Callable,
)

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from lando.api.legacy.phabricator import PhabricatorClient
from lando.main.models.profile import Profile


class LandoOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    """An extended OIDC auth backend that manipulates the user profile."""

    @staticmethod
    def _update_user_profile_permissions(user_profile: Profile, claims: dict):
        # Store user info in the user profile.
        user_profile.userinfo = claims
        user_profile.save()

        if settings.ENVIRONMENT != "localdev":
            # Update user permissions.
            user_profile.update_permissions()

    @staticmethod
    def _get_or_create_user_profile(user: User) -> Profile:
        # Check if there is an existing user profile, create it if not.
        try:
            user_profile = user.profile
        except User.profile.RelatedObjectDoesNotExist:
            user_profile = Profile(user=user)
            user_profile.save()
        return user_profile

    def post_auth_hook(self, user: User, claims: dict):
        """Perform user profile related tasks upon login."""
        user_profile = self._get_or_create_user_profile(user)
        self._update_user_profile_permissions(user_profile, claims)

    def create_user(self, claims: dict) -> User:
        user = super().create_user(claims)
        self.post_auth_hook(user, claims)
        return user

    def update_user(self, user: User, claims: dict) -> User:
        self.post_auth_hook(user, claims)
        return super().update_user(user, claims)


def require_authenticated_user(f):
    """
    Decorator which requires a user to be authenticated.

    Raises a PermissionError if a request is by an unauthenticated user.
    """

    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionError
        return f(request, *args, **kwargs)

    return wrapper


class require_permission:
    """
    Decorator that raises a PermissionError if a user is missing the given permission.
    """

    def __init__(self, permission):
        self.required_permission = permission

    def __call__(self, f: Callable) -> Callable:
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(f"main.{self.required_permission}"):
                raise PermissionError()
            return f(request, *args, **kwargs)


class require_phabricator_api_key:
    """Decorator which requires and verifies the phabricator API Key.

    If a user's API key is not available and optional is False, then
    an HTTP 401 response will be returned.

    The user's API key will be verified to be valid, if it is not an
    HTTP 403 response will be returned..

    If the optional parameter is True and no API key is provided, a default key
    will be used. If an API key is provided it will still be verified.

    If `provide_client=True`, the first argument is a PhabricatorClient using
    this API Key.
    """

    def __init__(self, optional: bool = False, provide_client: bool = True):
        self.optional = optional
        self.provide_client = provide_client

    def __call__(self, f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if (
                user.is_authenticated
                and hasattr(user, "profile")
                and user.profile.phabricator_api_key
            ):
                api_key = user.profile.phabricator_api_key
            else:
                api_key = None

            if api_key is None and not self.optional:
                return HttpResponse("Phabricator API key is required", status=401)

            phab = PhabricatorClient(
                settings.PHABRICATOR_URL,
                api_key or settings.PHABRICATOR_UNPRIVILEGED_API_KEY,
            )
            if api_key is not None and not phab.verify_api_token():
                return HttpResponse("Phabricator API key is invalid", status=403)

            if self.provide_client:
                return f(phab, request, *args, **kwargs)
            else:
                return f(request, *args, **kwargs)

        return wrapped
