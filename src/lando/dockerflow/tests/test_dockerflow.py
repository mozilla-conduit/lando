import pytest


@pytest.mark.django_db
def test_heartbeat_returns_200(client):
    assert client.get("/__heartbeat__").status_code == 200


@pytest.mark.django_db
def test_dockerflow_lb_endpoint_returns_200(client):
    assert client.get("/__lbheartbeat__").status_code == 200


@pytest.mark.django_db
def test_dockerflow_version_endpoint_response(client, lando_version):
    response = client.get("/__version__")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


@pytest.mark.django_db
def test_dockerflow_version_matches_disk_contents(client, lando_version):
    expected_json = {"version": lando_version}
    response = client.get("/__version__")

    assert response.status_code == 200
    assert response.json() == expected_json
