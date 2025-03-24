import pytest

from lando.ui.legacy.forms import UserSettingsForm


@pytest.mark.parametrize(
    "phabricator_api_key,is_valid",
    [
        ("", True),
        ("api-123456789012345678901234567x", True),
        ("api-123", False),
        ("xxx", False),
        ("xxx-123456789012345678901234567x", False),
        ("api-123456789012345678901234567X", False),
    ],
)
def test_user_settings(phabricator_api_key, is_valid):  # noqa: ANN001
    form = UserSettingsForm({"phabricator_api_key": phabricator_api_key})
    assert form.is_valid() == is_valid
