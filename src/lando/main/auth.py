import functools
import logging
from typing import (
    Callable,
)

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from lando.environments import Environment
from lando.main.models.profile import Profile, filter_claims
from lando.utils.phabricator import PhabricatorClient

logger = logging.getLogger(__name__)


class LandoOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    """An extended OIDC auth backend that manipulates the user profile."""

    @staticmethod
    def _update_user_profile_permissions(user_profile: Profile, claims: dict):
        # Store useful user info in the user profile.
        user_profile.userinfo = filter_claims(claims)
        user_profile.save()

        if settings.ENVIRONMENT == Environment.local:
            # Add all SCM permissions to this user.
            # NOTE: This is here mainly because when using Lando locally, userinfo
            # does not actually contain any group membership information.
            scm_permissions = user_profile.get_all_scm_permissions()
            for permission in scm_permissions.values():
                user_profile.user.user_permissions.add(permission)
        else:
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


def require_authenticated_user(f: Callable) -> Callable:
    """
    Decorator which requires a user to be authenticated.

    Raises a `PermissionDenied` if a request is by an unauthenticated user.
    """

    @functools.wraps(f)
    def wrapper(request: WSGIRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication is required")
        return f(request, *args, **kwargs)

    return wrapper


def force_auth_refresh(f: Callable) -> Callable:
    """
    Decorator which forces authenticated session to be refreshed.
    """

    def wrapper(*args, **kwargs):
        """Set oidc_id_token_expiration to 0, forcing session refresh."""
        # First check that SessionRefresh is indeed enabled.
        if "mozilla_django_oidc.middleware.SessionRefresh" not in settings.MIDDLEWARE:
            raise RuntimeError("SessionRefresh middleware required but is not enabled.")

        # Find the request in the arguments. This is needed in case this decorator
        # is used in class-based views. The request would be the first argument that
        # is a WSGIRequest instance.
        request = [arg for arg in args if isinstance(arg, WSGIRequest)][0]
        logger.debug(
            f"Prior OIDC expiration {request.session.get('oidc_id_token_expiration')}"
        )
        request.session["oidc_id_token_expiration"] = 0
        return f(*args, **kwargs)

    return wrapper


class require_permission:
    """
    Decorator that raises a `PermissionDenied` if a user is missing the given permission.
    """

    def __init__(self, permission: str):
        self.required_permission = permission

    def __call__(self, f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(request: WSGIRequest, *args, **kwargs) -> HttpResponse:
            if not request.user.has_perm(f"main.{self.required_permission}"):
                raise PermissionDenied()
            return f(request, *args, **kwargs)

        return wrapper


class require_phabricator_api_key:
    """Decorator which requires and verifies the Phabricator API Key.

    If a user's API key is not available and optional is False, then
    an HTTP 401 response will be returned.

    The user's API key will be verified to be valid, if it is not an
    HTTP 403 response will be returned.

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
        def wrapped(request: WSGIRequest, *args, **kwargs) -> HttpResponse:
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
