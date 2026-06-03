import pytest
from django.contrib.auth.models import AnonymousUser, Group, User

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
