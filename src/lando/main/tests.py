import pytest
from django.contrib.auth.models import User

from lando.main.auth import LandoOIDCAuthenticationBackend
from lando.main.models.profile import CLAIM_GROUPS_KEY


@pytest.mark.parametrize(
    "groups,has_scm_conduit_perm",
    [
        # User should have permission if they have the active/all groups.
        (["active_scm_conduit", "all_scm_conduit"], True),
        # User should not have permission in all other cases.
        (["expired_scm_conduit", "all_scm_conduit"], False),
        (["expired_scm_conduit", "all_scm_conduit", "active_scm_conduit"], False),
        (["all_scm_conduit"], False),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_LandoOIDCAuthenticationBackend__update_user_scm_access(
    monkeypatch, groups, has_scm_conduit_perm
):
    backend = LandoOIDCAuthenticationBackend()
    user = User.objects.create_user(username="test_user", password="test_password")
    backend.update_user(user, {CLAIM_GROUPS_KEY: groups})
    assert user.has_perm("main.scm_conduit") is has_scm_conduit_perm
