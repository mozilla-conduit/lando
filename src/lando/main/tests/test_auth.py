import pytest
from django.contrib.auth.models import AnonymousUser, Group, User
from django.urls import reverse

from lando.main.auth import CONDUIT_ADMIN_GROUP_NAME, user_is_conduit_admin


@pytest.mark.parametrize(
    "is_staff,in_group,expected",
    (
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ),
)
@pytest.mark.django_db
def test_user_is_conduit_admin(is_staff: bool, in_group: bool, expected: bool):
    user = User.objects.create_user("testuser", is_staff=is_staff)
    if in_group:
        group, _ = Group.objects.get_or_create(name=CONDUIT_ADMIN_GROUP_NAME)
        group.user_set.add(user)

    assert user_is_conduit_admin(user) is expected, (
        f"A staff={is_staff}, in_group={in_group} user should "
        f"{'' if expected else 'not '}be a Conduit admin."
    )


@pytest.mark.django_db
def test_user_is_conduit_admin_anonymous():
    assert user_is_conduit_admin(AnonymousUser()) is False, (
        "An unauthenticated user should not be a Conduit admin."
    )


@pytest.mark.parametrize(
    "logged_in,error,expected_location",
    (
        (True, "login_required", "/oidc/authenticate/?next=%2FD1234%2F%3Ftab%3Dstack"),
        (True, "access_denied", "/"),
        # A failed interactive login must not restart login, or it could loop.
        (False, "login_required", "/"),
    ),
)
@pytest.mark.django_db
def test_oidc_callback_failed_silent_refresh_returns_to_page(
    client, logged_in: bool, error: str, expected_location: str
):
    if logged_in:
        client.force_login(User.objects.create_user("testuser"))
    session = client.session
    session["oidc_login_next"] = "/D1234/?tab=stack"
    session["oidc_states"] = {"some-state": {"nonce": "n", "code_verifier": None}}
    session.save()

    response = client.get(
        reverse("oidc_authentication_callback"),
        {"error": error, "state": "some-state"},
    )

    assert response.status_code == 302
    assert response["Location"] == expected_location, (
        f"A `{error}` callback error should redirect to `{expected_location}`."
    )
    assert "_auth_user_id" not in client.session, (
        "The user should be logged out after a failed OIDC callback."
    )


@pytest.mark.django_db
def test_oidc_failed_silent_refresh_then_failed_login_does_not_loop(client):
    client.force_login(User.objects.create_user("testuser"))
    session = client.session
    session["oidc_login_next"] = "/D1234/"
    session.save()
    callback_url = reverse("oidc_authentication_callback")

    response = client.get(callback_url, {"error": "login_required"})
    assert response["Location"] == "/oidc/authenticate/?next=%2FD1234%2F", (
        "A failed silent refresh should start an interactive login."
    )

    client.get(response["Location"])
    assert client.session["oidc_login_next"] == "/D1234/", (
        "The interactive login should preserve the requested page."
    )

    response = client.get(callback_url, {"error": "login_required"})
    assert response["Location"] == "/", (
        "A failed interactive login should not restart login."
    )
