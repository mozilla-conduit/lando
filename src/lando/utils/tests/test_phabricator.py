import pytest
from django.conf import settings

from lando.utils.phabricator import get_phabricator_client

USER_KEY = "api-userprovidedkey00000000000000"


@pytest.mark.parametrize(
    "privileged, api_key, expected_token",
    (
        (False, USER_KEY, USER_KEY),
        (True, USER_KEY, USER_KEY),
        (False, None, settings.PHABRICATOR_UNPRIVILEGED_API_KEY),
        (True, None, settings.PHABRICATOR_ADMIN_API_KEY),
    ),
    ids=(
        "unprivileged-with-explicit-key",
        "privileged-with-explicit-key",
        "unprivileged-fallback",
        "privileged-fallback",
    ),
)
def test_get_phabricator_client_api_key_selection(privileged, api_key, expected_token):
    """The client should use the provided `api_key` when given, and fall back
    to the appropriate system key otherwise."""
    client = get_phabricator_client(privileged=privileged, api_key=api_key)
    assert client.api_token == expected_token, (
        f"`get_phabricator_client(privileged={privileged}, api_key={api_key!r})` "
        f"should produce a client with `api_token` `{expected_token!r}`."
    )
