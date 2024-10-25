import base64
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.http import HttpResponse

from lando.main.auth import LandoOIDCAuthenticationBackend, require_phabricator_api_key
from lando.main.models.profile import CLAIM_GROUPS_KEY, Profile
from lando.utils.phabricator import PhabricatorClient


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


@pytest.mark.django_db(transaction=True)
def test_LandoOIDCAuthenticationBackend__update_user_filter_claims():
    backend = LandoOIDCAuthenticationBackend()
    user = User.objects.create_user(username="test_user", password="test_password")
    backend.update_user(
        user,
        {
            "picture": "test picture",
            "some_other_field": "test",
            CLAIM_GROUPS_KEY: ["scm_level_1", "something_else"],
        },
    )
    assert "some_other_fields" not in user.profile.userinfo
    assert "something_else" not in user.profile.userinfo[CLAIM_GROUPS_KEY]


def noop(phab, *args, **kwargs):
    response = HttpResponse(status=200)
    response.body = phab
    return response


@pytest.mark.parametrize(
    "optional,valid_key,status",
    [
        (False, None, 401),
        (False, False, 403),
        (False, True, 200),
        (True, None, 200),
        (True, False, 403),
        (True, True, 200),
    ],
)
def test_require_phabricator_api_key(monkeypatch, optional, valid_key, status):
    fake_request = MagicMock()
    fake_request.user.profile.phabricator_api_key = None
    fake_request.user.is_authenticated = True

    if valid_key is not None:
        fake_request.user.profile.phabricator_api_key = "custom-key"
        monkeypatch.setattr(
            "lando.main.auth.PhabricatorClient.verify_api_token",
            lambda *args, **kwargs: valid_key,
        )

    resp = require_phabricator_api_key(optional=optional)(noop)(fake_request)
    if status == 200:
        assert isinstance(resp.body, PhabricatorClient)
    if valid_key:
        assert resp.body.api_token == "custom-key"

    assert resp.status_code == status


@pytest.mark.django_db(transaction=True)
def test_phabricator_api_key_encryption():
    user = User.objects.create_user(username="test_user", password="test_password")
    profile = Profile.objects.create(user=user)

    assert profile.phabricator_api_key == ""

    # Set an arbitrary key.
    key = "test-key"
    profile.save_phabricator_api_key(key)
    assert key.encode("utf-8") not in profile.encrypted_phabricator_api_key
    assert base64.b64decode(profile.encrypted_phabricator_api_key)
    assert profile.phabricator_api_key == key

    # Clear the key
    profile.clear_phabricator_api_key()
    assert profile.phabricator_api_key == ""
