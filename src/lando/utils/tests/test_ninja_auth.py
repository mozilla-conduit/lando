from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings

from lando.environments import Environment
from lando.utils.ninja_auth import api


@pytest.mark.django_db()
@patch("lando.utils.ninja_auth.AccessTokenAuth.authenticate")
def test_authentication_valid_token(
    mock_authenticate: MagicMock, ninja_api_client: Callable
):
    mock_authenticate.return_value = User(username="testuser", is_active=True)

    response = ninja_api_client(api).get(
        "/__userinfo__",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return a User.
        headers={"AuThOrIzAtIoN": "bEaReR valid_token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 200, "Valid token should result in 200"


@pytest.mark.django_db()
@patch("lando.main.auth.AccessTokenLandoOIDCAuthenticationBackend.get_userinfo")
def test_authentication_valid_token_non_existent_user(
    mock_get_userinfo: MagicMock, client: Client
):
    """Checks that users are created correctly when first authenticating with a token."""
    mock_get_userinfo.return_value = {
        "dn": None,
        "email": "api-user@example.com",
        "email_aliases": None,
        "email_verified": True,
        "family_name": "user",
        "given_name": "api",
        "https://sso.mozilla.com/claim/groups": [
            "active_scm_level_1",
            "all_scm_level_1",
            "all_scm_level_3",
            "everyone",
        ],
        "name": "api-user",
        "nickname": "api-user",
        "organizationUnits": None,
        "picture": "https://example.com/api-user.png",
        "sub": "ad|Mozilla-LDAP|api-user",
        "updated_at": "2026-01-23T00:55:19.962Z",
    }

    user_count = len(User.objects.all())

    response = client.get(
        "/auth/__userinfo__",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return a User.
        headers={"AuThOrIzAtIoN": "bEaReR valid_token"},
    )

    assert mock_get_userinfo.called, "get_userinfo should be called"
    assert response.status_code == 200, "Valid token should result in 200"

    assert len(User.objects.all()) == user_count + 1, "No new user created"

    user = User.objects.last()

    assert hasattr(user, "profile"), "Token-created user is missing its Profile"

    assert user.has_perm(
        "main.scm_level_1"
    ), "User is missing scm_level_1 permission, despite it being active"
    assert not user.has_perm(
        "main.scm_level_3"
    ), "User has scm_level_3 permission, despite it being inactive"


@pytest.mark.django_db()
def test_authentication_no_token(client: Client, ninja_api_client: Callable):
    response = ninja_api_client(api).get("/__userinfo__")
    assert response.status_code == 401, "Missing token should result in 401"


@pytest.mark.django_db()
@patch("lando.utils.ninja_auth.AccessTokenAuth.authenticate")
def test_authentication_invalid_token(
    mock_authenticate: MagicMock, ninja_api_client: Callable
):
    mock_authenticate.return_value = None

    response = ninja_api_client(api).get(
        "/__userinfo__",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return None.
        headers={"AuThOrIzAtIoN": "bEaReR invalid_token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 401, "Invalid token should result in 401"


@pytest.mark.django_db()
@override_settings(ENVIRONMENT=Environment("production"))
@patch("lando.utils.ninja_auth.AccessTokenAuth.authenticate")
def test_userinfo_not_in_prod(mock_authenticate: MagicMock, ninja_api_client: Callable):
    mock_authenticate.return_value = User(username="testuser", is_active=True)
    response = ninja_api_client(api).get(
        "/__userinfo__", headers={"AuThOrIzAtIoN": "bEaReR valid_token"}
    )

    assert response.status_code == 404, "__userinfo__ should not be available in prod"
