import pytest
from django.contrib.auth.models import User
from django.test import Client

from lando.main.models.profile import Profile

VALID_API_KEY = "api-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def post_api_key(client: Client, api_key: str = VALID_API_KEY):
    """Submit an API key to the `manage_api_key` view."""
    return client.post(
        "/manage_api_key/",
        data={"phabricator_api_key": api_key, "reset_key": False},
    )


@pytest.mark.django_db(transaction=True)
def test_manage_api_key_happy_path(
    client: Client,
    user,
    phabdouble,
):
    """A successful API key update stores the new key and PHID on the profile."""
    phab_user = phabdouble.user(username="phab_user", api_key=VALID_API_KEY)

    client.force_login(user)
    response = post_api_key(client)

    assert response.status_code == 200, (
        "A valid API key with a unique PHID should be accepted."
    )
    assert response.json() == {"success": True}, "Response body should report success."

    user.profile.refresh_from_db()
    assert user.profile.phabricator_phid == phab_user["phid"], (
        "Profile should store the PHID reported by `user.whoami`."
    )
    assert user.profile.phabricator_api_key == VALID_API_KEY, (
        "Profile should store the submitted API key."
    )


@pytest.mark.django_db(transaction=True)
def test_manage_api_key_phid_conflict_returns_error(
    client: Client,
    user,
    phabdouble,
):
    """Linking an API key whose PHID already belongs to another user returns a 400."""
    phab_user = phabdouble.user(username="phab_user", api_key=VALID_API_KEY)

    # Another Lando user already owns this Phabricator PHID.
    other_user = User.objects.create_user(
        username="other_user", email="other@example.org"
    )
    Profile.objects.create(user=other_user, phabricator_phid=phab_user["phid"])

    client.force_login(user)
    response = post_api_key(client)

    assert response.status_code == 400, (
        "Linking an API key whose PHID is owned by another user should return 400."
    )
    assert response.json() == {
        "errors": {
            "phabricator_api_key": [
                "This Phabricator account is already linked to another Lando user."
            ]
        }
    }, "Response body should describe the PHID conflict."
