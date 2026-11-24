import requests_mock
from django.conf import settings

from lando.api.legacy.bmo import (
    api_request,
    held_for_security_team,
    is_tick_tock,
    security_keyword,
)


def test_api_request_sends_configured_user_agent():
    with requests_mock.mock() as mocker:
        mocker.get(f"{settings.BUGZILLA_URL}/rest/bug", json={"bugs": []})

        response = api_request("GET", "bug")

        assert response.request.headers["User-Agent"] == settings.HTTP_USER_AGENT, (
            "`api_request` should send the `HTTP_USER_AGENT` from settings."
        )


def test_security_keyword_defaults_to_security_keywords():
    assert (
        security_keyword({"keywords": ["sec-high", "sec-critical"]}) == "sec-critical"
    )
    assert security_keyword({"keywords": ["tick-tock"]}) is None


def test_security_keyword_accepts_custom_keywords():
    assert security_keyword({"keywords": ["tick-tock"]}, ("tick-tock",)) == "tick-tock"


def test_is_tick_tock():
    assert is_tick_tock({"keywords": ["tick-tock"]})
    assert not is_tick_tock({"keywords": ["sec-high"]})


def test_held_for_security_team_fails_closed():
    assert held_for_security_team(None, set())
    assert not held_for_security_team({}, set())
    assert held_for_security_team({}, {1})
    assert held_for_security_team({1: {"keywords": ["tick-tock"]}}, {1})
