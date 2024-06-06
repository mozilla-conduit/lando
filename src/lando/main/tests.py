import pytest
from django.contrib.auth.models import User

from lando.main.auth import LandoOIDCAuthenticationBackend
from lando.main.models.profile import CLAIM_GROUPS_KEY


@pytest.mark.django_db(transaction=True)
def test_LandoOIDCAuthenticationBackend__update_user_scm_access(monkeypatch):
    backend = LandoOIDCAuthenticationBackend()
    user = User.objects.create_user(username="test_user", password="test_password")

    # Test that having the active/all groups will add the correct permission.
    groups = ["active_scm_conduit", "all_scm_conduit"]
    claims = {CLAIM_GROUPS_KEY: groups}
    backend.update_user(user, claims)
    assert user.has_perm("main.scm_conduit")

    # Test that having the expired group will remove the permission.
    groups = ["expired_scm_conduit", "all_scm_conduit"]
    claims = {CLAIM_GROUPS_KEY: groups}
    user = User.objects.get(username="test_user")
    backend.update_user(user, claims)
    assert not user.has_perm("main.scm_conduit")

    # Test that an ambiguous situation will result in no permission.
    groups = ["expired_scm_conduit", "all_scm_conduit", "active_scm_conduit"]
    claims = {CLAIM_GROUPS_KEY: groups}
    user = User.objects.get(username="test_user")
    backend.update_user(user, claims)
    assert not user.has_perm("main.scm_conduit")
