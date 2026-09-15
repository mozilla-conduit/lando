import pytest

from lando.ui.legacy.forms import (
    TransplantRequestForm,
    UserSettingsForm,
)


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
def test_user_settings(phabricator_api_key, is_valid):
    form = UserSettingsForm({"phabricator_api_key": phabricator_api_key})
    assert form.is_valid() == is_valid


@pytest.mark.parametrize(
    "data,mailbox,errors",
    (
        ({"author_name": "", "author_email": "", "landing_path": "1"}, None, None),
        (
            {"author_name": "test", "author_email": "", "landing_path": "1"},
            None,
            {"author_email": ["This field is required."]},
        ),
        (
            {
                "author_name": "",
                "author_email": "test@example.com",
                "landing_path": "1",
            },
            None,
            {"author_name": ["This field is required."]},
        ),
        (
            {"author_name": "", "author_email": "test", "landing_path": "1"},
            None,
            {
                "author_email": [
                    "Enter a valid email address.",
                ],
            },
        ),
        (
            {
                "author_name": "test",
                "author_email": "test@example.com",
                "landing_path": "1",
            },
            ("test", "test@example.com"),
            None,
        ),
        (
            {
                "author_name": "test",
                "author_email": "hackbot@mozilla.tld",
                "landing_path": "1",
            },
            None,
            {
                "author_email": [
                    "The email provided is not allowed",
                    "This field is required.",
                ]
            },
        ),
    ),
)
def test__TransplantRequestForm(data, mailbox, errors):
    form = TransplantRequestForm(data)
    if not errors:
        assert form.is_valid()
        assert form.cleaned_data["mailbox"] == mailbox
        if mailbox:
            assert "author_name" not in form.cleaned_data
            assert "author_email" not in form.cleaned_data
    else:
        assert form.errors == errors
