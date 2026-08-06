import requests_mock
from django.conf import settings

from lando.api.legacy.bmo import api_request


def test_api_request_sends_configured_user_agent():
    with requests_mock.mock() as mocker:
        mocker.get(f"{settings.BUGZILLA_URL}/rest/bug", json={"bugs": []})

        response = api_request("GET", "bug")

        assert response.request.headers["User-Agent"] == settings.HTTP_USER_AGENT, (
            "`api_request` should send the `HTTP_USER_AGENT` from settings."
        )
