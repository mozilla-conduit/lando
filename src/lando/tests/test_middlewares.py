import pytest
from django.test.client import Client

from lando.main.models import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)
from lando.middleware import url_origin


@pytest.mark.parametrize(
    "url,expected",
    (
        (
            "https://fx-trains.herokuapp.com/api/lando/uplift/train/",
            "https://fx-trains.herokuapp.com",
        ),
        ("http://example.test:8000/path", "http://example.test:8000"),
        ("/api/lando/uplift/train/", ""),
        ("//example.test/path", ""),
        ("", ""),
    ),
)
def test_url_origin(url: str, expected: str):
    assert url_origin(url) == expected, (
        f"`url_origin({url!r})` should return {expected!r}."
    )


@pytest.mark.parametrize(
    "path,available_in_maintenance",
    (
        ("/treestatus/", False),
        ("/api/treestatus/trees", True),
        ("/api/treestatus/stack", True),
    ),
)
@pytest.mark.django_db
def test_maintenance_mode_treestatus_api_exception(
    client: Client, path: str, available_in_maintenance: bool
):
    """The Treestatus API stays available while Lando is under maintenance."""
    ConfigurationVariable.set(
        ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "1"
    )

    response = client.get(path)

    if available_in_maintenance:
        assert response.status_code == 200, (
            f"`{path}` should be served during maintenance."
        )
        assert "maintenance" not in response.content.decode(), (
            f"`{path}` should not return the maintenance page during maintenance."
        )
    else:
        assert "maintenance" in response.content.decode(), (
            f"`{path}` should return the maintenance page during maintenance."
        )


@pytest.mark.parametrize(
    "origin,path,expected_present",
    (
        ("", "/", False),
        ("", "/landing_jobs/1", False),
        ("treeherder", "/landing_jobs/1", True),
        ("", "/api/1", False),
        ("treeherder", "/api/1", False),
    ),
)
@pytest.mark.django_db
def test_cors_acao_header(
    client: Client, origin: str, path: str, expected_present: bool
):

    headers = {}
    if origin is not None:
        headers.update({"origin": origin})

    resp = client.get(path, headers=headers)

    if expected_present:
        assert "access-control-allow-origin" in resp.headers, (
            f"Missing ACAO header for request from '{origin}' to '{path}'"
        )
        assert resp.headers["access-control-allow-origin"] == "*", (
            f"Unexpected ACAO header value {resp.headers['access-control-allow-origin']} for request from '{origin}' to '{path}'"
        )
    else:
        assert "access-control-allow-origin" not in resp.headers, (
            f"Unexpected ACAO header present for request from '{origin}' to '{path}'"
        )
