from lando.ui.legacy.forms import UserSettingsForm
from lando.ui.legacy.usersettings import manage_phab_api_token_cookie


def test_setting_token(app):
    form = UserSettingsForm(phab_api_token="phab_token", reset_phab_api_token=False)
    response = manage_phab_api_token_cookie(form, dict())
    assert "phabricator-api-token=phab_token" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert response.json["phab_api_token_set"]


def test_resetting_token(app):
    form = UserSettingsForm(phab_api_token="", reset_phab_api_token=True)
    response = manage_phab_api_token_cookie(form, dict())
    assert "phabricator-api-token=;" in response.headers["Set-Cookie"]
    assert not response.json["phab_api_token_set"]

    form = UserSettingsForm(phab_api_token="token", reset_phab_api_token=True)
    response = manage_phab_api_token_cookie(form, dict())
    assert "phabricator-api-token=;" in response.headers["Set-Cookie"]
    assert not response.json["phab_api_token_set"]


def test_phab_api_token_untouched(app):
    form = UserSettingsForm(phab_api_token="", reset_phab_api_token=False)
    response = manage_phab_api_token_cookie(form, dict())
    assert "Set-Cookie" not in response.headers
    assert not response.json["phab_api_token_set"]
