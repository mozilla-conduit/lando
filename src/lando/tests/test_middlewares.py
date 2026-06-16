import pytest
from django.test.client import Client

from lando.middleware import csp_origin


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
def test_csp_origin(url: str, expected: str):
    assert csp_origin(url) == expected, (
        f"`csp_origin({url!r})` should return {expected!r}."
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
