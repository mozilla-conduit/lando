import pytest
from lando.tests.test_version import generate_version_file  # noqa: F401


@pytest.mark.django_db
def test_heartbeat_returns_200(client):
    assert client.get("/__heartbeat__").status_code == 200


def test_dockerflow_lb_endpoint_returns_200(client):
    assert client.get("/__lbheartbeat__").status_code == 200


def test_dockerflow_version_endpoint_response(client, generate_version_file):
    response = client.get("/__version__")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_dockerflow_version_matches_disk_contents(client, generate_version_file):
    from lando.version import version

    expected_json = {"version": version}
    response = client.get("/__version__")

    assert response.status_code == 200
    assert response.json() == expected_json
