import functools
import logging
from typing import (
    Callable,
)

from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

# requests is a transitive dependency of mozilla-django-oidc.
from lando.environments import Environment
from lando.main.models.profile import Profile, filter_claims
from lando.utils.phabricator import PhabricatorClient

logger = logging.getLogger(__name__)


class PhabricatorTokenAuthenticationBackend(BaseBackend):
    """Authenticate a user based on their Phabricator PHID and token."""

    @staticmethod
    def get_phab_user(phabricator_token: str) -> dict | None:
        """Verify a Phabricator token and return the `user.whoami` data."""
        phab = PhabricatorClient(settings.PHABRICATOR_URL, phabricator_token)

        if not phab.verify_api_token():
            return None

        return phab.call_conduit("user.whoami")

    @staticmethod
    def get_user_by_phid(token_phid: str) -> User | None:
        """Look up a local user by Phabricator PHID."""
        if not token_phid:
            return None

        try:
            return User.objects.select_related("profile").get(
                profile__phabricator_phid=token_phid
            )
        except User.DoesNotExist:
            return None

    @staticmethod
    def get_user_by_email(email: str) -> User | None:
        """Look up a local user by email."""
        try:
            return User.objects.select_related("profile").get(email=email)
        except User.DoesNotExist:
            return None

    def authenticate(self, request: WSGIRequest, phabricator_token: str) -> User:
        """Given a Phabricator token, validate and attempt to match with local user."""
        logger.debug("Authenticating Phabricator token via `user.whoami`.")
        token_user = self.get_phab_user(phabricator_token)
        if not token_user:
            logger.debug("Phabricator token authentication failed: token is not valid.")
            raise PermissionDenied()

        token_phid = token_user["phid"]
        logger.debug("Phabricator token resolved to PHID `%s`.", token_phid)

        lando_user = self.get_user_by_phid(token_phid)
        if not lando_user:
            logger.debug(
                "No user found for PHID `%s`, falling back to email lookup.",
                token_phid,
            )
            email = token_user.get("primaryEmail")
            if email:
                lando_user = self.get_user_by_email(email)

        if not lando_user:
            logger.debug(
                "Phabricator token authentication failed: "
                "no local user found for PHID `%s`.",
                token_phid,
            )
            raise PermissionDenied()

        profile = lando_user.profile
        if not profile.phabricator_api_key:
            logger.debug(
                "Phabricator token authentication failed: "
                "user `%s` has no stored Phabricator API key "
                "for secondary verification.",
                lando_user.username,
            )
            raise PermissionDenied()

        logger.debug("Verifying stored API key for user `%s`.", lando_user.username)
        matching_user = self.get_phab_user(profile.phabricator_api_key)
        if token_user != matching_user:
            logger.debug(
                "Phabricator token authentication failed: "
                "stored API key and provided token resolve to different users.",
            )
            raise PermissionDenied()

        if not profile.phabricator_phid:
            logger.debug(
                "Back-populating PHID `%s` on profile for user `%s`.",
                token_phid,
                lando_user.username,
            )
            profile.phabricator_phid = token_phid
            profile.save()

        logger.debug(
            "Phabricator token authentication succeeded for user `%s`.",
            lando_user.username,
        )
        return lando_user

    def get_user(self, user_id: int) -> User:
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


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
        """Create user with given claims then run post auth hooks."""
        user = super().create_user(claims)
        self.post_auth_hook(user, claims)
        return user

    def update_user(self, user: User, claims: dict) -> User:
        """Run post auth hooks then update given user with given claims."""
        self.post_auth_hook(user, claims)
        return super().update_user(user, claims)


class AccessTokenLandoOIDCAuthenticationBackend(LandoOIDCAuthenticationBackend):
    """Authenticates a user based on a Bearer access_token.

    Note, this is a shim replacement of the mozilla_django_oidc.auth.TokenOIDCAuthenticationBackend.
    """

    def authenticate(self, request: WSGIRequest, **kwargs) -> User | None:
        # If a bearer token is present in the request, use it to authenticate the user.
        if authorization := request.META.get("HTTP_AUTHORIZATION"):
            scheme, token = authorization.split(maxsplit=1)
            if scheme.lower() == "bearer":
                try:
                    # get_or_create_user and get_userinfo uses neither id_token nor payload.
                    return self.get_or_create_user(token, None, None)
                except SuspiciousOperation as exc:
                    logger.warning("failed to get or create user: %s", exc)
                    return None

        return None


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
                raise PermissionDenied(
                    f"Permission {self.required_permission} is required"
                )
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
