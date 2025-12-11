from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings

from lando.environments import Environment
from lando.utils.auth import api


@pytest.mark.django_db()
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
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
def test_authentication_no_token(client: Client, ninja_api_client: Callable):
    response = ninja_api_client(api).get("/__userinfo__")
    assert response.status_code == 401, "Missing token should result in 401"


@pytest.mark.django_db()
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
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


@override_settings(ENVIRONMENT=Environment("production"))
@patch("lando.utils.auth.AccessTokenAuth.authenticate")
def test_userinfo_not_in_prod(mock_authenticate: MagicMock, ninja_api_client: Callable):
    mock_authenticate.return_value = User(username="testuser", is_active=True)
    response = ninja_api_client(api).get(
        "/__userinfo__", headers={"AuThOrIzAtIoN": "bEaReR valid_token"}
    )

    assert response.status_code == 404, "__userinfo__ should not be available in prod"
