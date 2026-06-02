import pytest
from django.contrib.auth.models import AnonymousUser, Group, User
from django.test.client import Client

from lando.middleware import CONDUIT_ADMIN_GROUP_NAME, user_is_conduit_admin


@pytest.mark.parametrize(
    "origin,path,expected_present",
    (
        ("", "/", False),
        ("", "/landing_jobs/1", False),
        ("treeherder", "/landing_jobs/1", True),
        ("", "/api/1", False),
        ("treeherder", "/api/1", False),
    ),
)
@pytest.mark.django_db
def test_cors_acao_header(
    client: Client, origin: str, path: str, expected_present: bool
):

    headers = {}
    if origin is not None:
        headers.update({"origin": origin})

    resp = client.get(path, headers=headers)

    if expected_present:
        assert "access-control-allow-origin" in resp.headers, (
            f"Missing ACAO header for request from '{origin}' to '{path}'"
        )
        assert resp.headers["access-control-allow-origin"] == "*", (
            f"Unexpected ACAO header value {resp.headers['access-control-allow-origin']} for request from '{origin}' to '{path}'"
        )
    else:
        assert "access-control-allow-origin" not in resp.headers, (
            f"Unexpected ACAO header present for request from '{origin}' to '{path}'"
        )


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
