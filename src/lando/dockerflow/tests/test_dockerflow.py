import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_heartbeat_returns_200(client):
    assert client.get("/__heartbeat__").status_code == 200


def test_dockerflow_lb_endpoint_returns_200(client):
    assert client.get("/__lbheartbeat__").status_code == 200


def test_dockerflow_version_endpoint_response(client):
    # The version file may or may not exist in the testing
    # environment yet, so we should explicitly generate it.
    call_command('generate_version_file')

    response = client.get("/__version__")

    assert response.status_code == 200
    assert response['Content-Type'] == "application/json"


def test_dockerflow_version_matches_disk_contents(client):
    # The version file may or may not exist in the testing
    # environment yet, so we should explicitly generate it.
    call_command('generate_version_file')

    from lando.version import version

    expected_json = {"version": version}
    response = client.get("/__version__")

    assert response.status_code == 200
    assert response.json() == expected_json
