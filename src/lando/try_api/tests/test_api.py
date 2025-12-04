from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from lando.try_api.api import api


@pytest.mark.skip()
@pytest.mark.django_db()
@patch("lando.try_api.api.AccessTokenAuth.authenticate")
def test_try_patches_scm1(
    mock_authenticate: MagicMock,
    scm_user: Callable,
    to_permissions: Callable,
    api_client: Callable,
):
    # user = scm_user(to_permissions(["scm_level_1"]), "password")
    user = scm_user([], "password")
    mock_authenticate.return_value = user

    request_payload = {
        # "repo": "some",
        # "base_commit": "0" * 40,
        # "base_commit_vcs": "git",
        # "patches": [
        #     "base64",
        #     "base64",
        # ],
        # "patch_format": "git-format-patch",
    }

    response = api_client(api).post(
        "/patches",
        # The value of the token doesn't actually matter, as the output is controlled by
        # the authenticator function, which we mock to return a User.
        data=request_payload,
        headers={"AuThOrIzAtIoN": "bEaReR valid_token"},
    )

    assert mock_authenticate.called, "Authentication backend should be called"
    assert response.status_code == 403, "Valid token without SCM1 should result in 403"
