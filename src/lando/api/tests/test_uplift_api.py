import json
from unittest import mock

import pytest

from lando.api.tests.test_uplift import CREATE_FORM_DATA, UPDATED_FORM_DATA
from lando.main.models.uplift import UpliftAssessment, UpliftRevision

ENDPOINT_URL = "/api/uplift/assessments/link"


@pytest.fixture
def phab_header(phabdouble, user, user_phab_api_key):
    phabdouble.user(
        username="test",
        email=user.email,
        api_key=user_phab_api_key,
    )
    return {"HTTP_X_PHABRICATOR_API_KEY": user_phab_api_key}


@pytest.mark.parametrize(
    "extra_headers, description",
    [
        ({}, "missing"),
        ({"HTTP_X_PHABRICATOR_API_KEY": "invalid-key"}, "invalid"),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_link_revision_unauthorized_api_key(
    client, phabdouble, extra_headers, description
):
    """Request with a missing or invalid API key should return 401."""
    response = client.post(
        ENDPOINT_URL,
        data=json.dumps({"revision_id": 123, "assessment_id": 1}),
        content_type="application/json",
        **extra_headers,
    )
    assert response.status_code == 401, f"{description} API key should return 401."
    body = response.json()
    assert "detail" in body, "Response body should contain a `detail` field."
    assert (
        body["detail"] == "Unauthorized"
    ), "Response `detail` should indicate the request was unauthorized."


@pytest.mark.django_db(transaction=True)
def test_link_revision_missing_fields(client, phab_header):
    """Request with missing fields should return 422."""
    response = client.post(
        ENDPOINT_URL,
        data=json.dumps({}),
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 422, "Missing required fields should return 422."


@pytest.mark.django_db(transaction=True)
def test_link_revision_assessment_not_found(client, phab_header):
    """Request referencing a non-existent assessment should return 404."""
    response = client.post(
        ENDPOINT_URL,
        data=json.dumps({"revision_id": 123, "assessment_id": 99999}),
        content_type="application/json",
        **phab_header,
    )
    assert response.status_code == 404, "Non-existent assessment should return 404."
    body = response.json()
    assert (
        "does not exist" in body["details"]
    ), "Error message should indicate the assessment was not found."


@mock.patch("lando.api.uplift_api.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db(transaction=True)
def test_link_revision_creates_new_link(mock_apply_async, client, phab_header, user):
    """Linking a new revision to an assessment should create an `UpliftRevision`."""
    assessment = UpliftAssessment.objects.create(user=user, **CREATE_FORM_DATA)

    response = client.post(
        ENDPOINT_URL,
        data=json.dumps(
            {
                "revision_id": 12345,
                "assessment_id": assessment.id,
            }
        ),
        content_type="application/json",
        **phab_header,
    )

    assert response.status_code == 201, "Successful link should return 201."
    body = response.json()
    assert body["revision_id"] == 12345, "Response should echo the revision ID."
    assert (
        body["assessment_id"] == assessment.id
    ), "Response should echo the assessment ID."
    assert body["created"] is True, "Response should indicate a new link was created."

    uplift_revision = UpliftRevision.objects.get(revision_id=12345)
    assert (
        uplift_revision.assessment_id == assessment.id
    ), "`UpliftRevision` should be linked to the correct assessment."

    mock_apply_async.assert_called_once()
    _, kwargs = mock_apply_async.call_args
    task_revision_id, conduit_json_str, task_user_id = kwargs["args"]
    assert (
        task_revision_id == 12345
    ), "Celery task should receive the linked revision ID."
    assert isinstance(
        conduit_json_str, str
    ), "Celery task should receive a serialized assessment payload."
    assert (
        task_user_id == assessment.user.id
    ), "Celery task should use the assessment owner's user ID."


@mock.patch("lando.api.uplift_api.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db(transaction=True)
def test_link_revision_replaces_existing_link(
    mock_apply_async, client, phab_header, user
):
    """Linking a revision that already has an assessment should replace it."""
    old_assessment = UpliftAssessment.objects.create(user=user, **CREATE_FORM_DATA)
    new_assessment = UpliftAssessment.objects.create(user=user, **UPDATED_FORM_DATA)

    UpliftRevision.objects.create(revision_id=6789, assessment=old_assessment)

    response = client.post(
        ENDPOINT_URL,
        data=json.dumps(
            {
                "revision_id": 6789,
                "assessment_id": new_assessment.id,
            }
        ),
        content_type="application/json",
        **phab_header,
    )

    assert response.status_code == 201, "Replacement link should return 201."
    body = response.json()
    assert (
        body["created"] is False
    ), "Response should indicate the link was updated, not created."

    uplift_revision = UpliftRevision.objects.get(revision_id=6789)
    assert (
        uplift_revision.assessment_id == new_assessment.id
    ), "`UpliftRevision` should now point to the new assessment."

    mock_apply_async.assert_called_once()
