from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings
from ninja.testing import TestClient

from lando.environments import Environment
from lando.try_api.api import api


@pytest.fixture()
def api_client():
    """Fixture to create a test client for the API."""
    # XXX If we pass the API directly, we get an error if we want to use this client
    # more than once (regardless of the scope of the fixture), as follows:
    #
    #    Looks like you created multiple NinjaAPIs or TestClients
    #    To let ninja distinguish them you need to set either unique version or urls_namespace
    #     - NinjaAPI(..., version='2.0.0')
    #     - NinjaAPI(..., urls_namespace='otherapi')
    #
    # Passing the pre-existing router to the TestClient instead, works. However, getting the
    # router is not golden-path.
    #
    return TestClient(api._routers[0][1])


@pytest.mark.django_db()
@patch("lando.try_api.api.LandoOIDCAuthenticationBackend.authenticate")
# @patch("lando.try_api.api.AccessTokenAuth.authenticate")
def test_authentication_valid_token(
    mock_authenticate: MagicMock, api_client: TestClient
):
    mock_authenticate.return_value = User(username="testuser", is_active=True)

    response = api_client.get(
        "/__userinfo__",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return a User.
        headers={"AuThOrIzAtIoN": "bEaReR valid_token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 200, "Valid token should result in 200"


@pytest.mark.django_db()
def test_authentication_no_token(client: Client, api_client: TestClient):
    response = api_client.get("/__userinfo__")
    assert response.status_code == 401, "Missing token should result in 401"


@pytest.mark.django_db()
# @patch("lando.try_api.api.LandoOIDCAuthenticationBackend.authenticate")
@patch("lando.try_api.api.AccessTokenAuth.authenticate")
def test_authentication_invalid_token(
    mock_authenticate: MagicMock, api_client: TestClient
):
    mock_authenticate.return_value = None

    response = api_client.get(
        "/__userinfo__",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return None.
        headers={"AuThOrIzAtIoN": "bEaReR invalid_token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 401, "Invalid token should result in 401"


@pytest.mark.django_db()
@override_settings(ENVIRONMENT=Environment("production"))
@patch("lando.try_api.api.GlobalAuth.authenticate")
def test_userinfo_not_in_prod(mock_authenticate: MagicMock, api_client: TestClient):
    mock_authenticate.return_value = User(username="testuser", is_active=True)
    response = api_client.get(
        "/__userinfo__", headers={"AuThOrIzAtIoN": "bEaReR valid_token"}
    )

    assert response.status_code == 404, "__userinfo__ should not be available in prod"
