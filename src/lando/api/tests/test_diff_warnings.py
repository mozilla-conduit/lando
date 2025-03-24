import json

import pytest

from lando.main.models.revision import (
    DiffWarning,
    DiffWarningGroup,
    DiffWarningStatus,
)


@pytest.fixture
def phab_header(phabdouble):  # noqa: ANN001, ANN201
    user = phabdouble.user(username="test")
    return {"HTTP_X_Phabricator_API_Key": user["apiKey"]}


@pytest.fixture
def diff_warning_data():  # noqa: ANN201
    return json.dumps({"message": "this is a test warning"})


@pytest.mark.django_db(transaction=True)
def test_diff_warning_create_bad_request(client):  # noqa: ANN001
    """Ensure a request that is missing required data returns an error."""
    response = client.post(
        "/api/diff_warnings/",
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_diff_warning_create_bad_request_no_message(
    client, phab_header  # noqa: ANN001
):
    """Ensure a request with incorrect data returns an error."""
    response = client.post(
        "/api/diff_warnings/",
        data={"revision_id": 1, "diff_id": 1, "group": "LINT", "data": {}},
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_diff_warning_create(client, diff_warning_data, phab_header):  # noqa: ANN001
    """Ensure that a warning is created correctly according to provided parameters."""
    response = client.post(
        "/api/diff_warnings/",
        data={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        content_type="application/json",
        **phab_header,
    )

    assert response.status_code == 201

    json_response = response.json()
    assert "id" in json_response

    pk = json_response["id"]
    warning = DiffWarning.objects.get(pk=pk)
    assert warning.group == DiffWarningGroup.LINT
    assert warning.revision_id == 1
    assert warning.diff_id == 1
    assert warning.status == DiffWarningStatus.ACTIVE
    assert warning.data == json.loads(diff_warning_data)


@pytest.mark.django_db(transaction=True)
def test_diff_warning_delete(client, diff_warning_data, phab_header):  # noqa: ANN001
    """Ensure that a DELETE request will archive a warning."""
    response = client.post(
        "/api/diff_warnings/",
        data={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 201
    pk = response.json()["id"]
    warning = DiffWarning.objects.get(pk=pk)
    assert warning.status == DiffWarningStatus.ACTIVE

    response = client.delete(
        f"/api/diff_warnings/{pk}/",
        content_type="application/json",
        **phab_header,
    )

    assert response.status_code == 200

    warning = DiffWarning.objects.get(pk=pk)
    assert warning.status == DiffWarningStatus.ARCHIVED


@pytest.mark.django_db(transaction=True, reset_sequences=True)
def test_diff_warning_get(client, diff_warning_data, phab_header):  # noqa: ANN001
    """Ensure that the API returns a properly serialized list of warnings."""
    response = client.post(
        "/api/diff_warnings/",
        data={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 201

    response = client.post(
        "/api/diff_warnings/",
        data={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 201

    # Create another diff warning in a different group.
    response = client.post(
        "/api/diff_warnings/",
        data={
            "revision_id": 1,
            "diff_id": 1,
            "group": "GENERAL",
            "data": diff_warning_data,
        },
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 201

    response = client.get(
        "/api/diff_warnings/",
        query_params={"revision_id": 1, "diff_id": 1, "group": "LINT"},
        **phab_header,
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "diff_id": 1,
            "group": "LINT",
            "id": 1,
            "revision_id": 1,
            "status": "ACTIVE",
            "data": json.loads(diff_warning_data),
        },
        {
            "diff_id": 1,
            "group": "LINT",
            "id": 2,
            "revision_id": 1,
            "status": "ACTIVE",
            "data": json.loads(diff_warning_data),
        },
    ]
