import pytest
import requests
import requests_mock
from django.conf import settings

from lando.utils.hackbot import (
    PATCH_ARTIFACT,
    RunDoc,
    RunRef,
    UpliftInputs,
    UpliftResult,
    UpliftSource,
    get_artifact,
    get_run,
    start_uplift_resolution,
)

RUN_ID = "0b6c1f4e-6c1a-4bd4-9a77-3c1d1f3f4d10"

INPUTS = UpliftInputs(
    target_branch="beta",
    sources=(UpliftSource.from_commit("a" * 40), UpliftSource.from_diff(1, 2)),
)


def test_uplift_inputs_to_json_leaves_out_unset_fields():
    assert INPUTS.to_json() == {
        "target_branch": "beta",
        "sources": (
            {"kind": "git", "commit": "a" * 40},
            {"kind": "phabricator", "revision_id": 1, "diff_id": 2},
        ),
    }, "Unset fields shouldn't be sent, so Hackbot uses its own defaults."


def test_start_uplift_resolution_posts_inputs_on_behalf_of_user():
    with requests_mock.mock() as mocker:
        mocker.post(
            f"{settings.HACKBOT_URL}/agents/uplift-resolve/runs",
            json={"run_id": RUN_ID, "agent": "uplift-resolve", "status": "pending"},
            status_code=201,
        )

        run = start_uplift_resolution(INPUTS, "dev@mozilla.com", "lando-key")

        request = mocker.last_request

    assert run == RunRef(run_id=RUN_ID, agent="uplift-resolve", status="pending"), (
        "The new run should be returned."
    )
    assert request.json() == {
        "target_branch": "beta",
        "sources": [
            {"kind": "git", "commit": "a" * 40},
            {"kind": "phabricator", "revision_id": 1, "diff_id": 2},
        ],
    }, "The agent inputs should be the request body, with `sources` as an array."
    assert request.headers["X-On-Behalf-Of"] == "dev@mozilla.com", (
        "The run should be attributed to the requesting user."
    )
    assert request.headers["X-API-Key"] == settings.HACKBOT_API_TOKEN, (
        "The request should authenticate with `HACKBOT_API_TOKEN`."
    )
    assert request.qs == {"dedupe_key": ["lando-key"]}, (
        "The dedupe key should make a retried request reuse its run."
    )


def test_get_run_parses_the_run_and_its_findings():
    findings = {"resolved": True, "confidence": "high", "summary": "Kept both."}

    with requests_mock.mock() as mocker:
        mocker.get(
            f"{settings.HACKBOT_URL}/runs/{RUN_ID}",
            json={
                "run_id": RUN_ID,
                "agent": "uplift-resolve",
                "status": "succeeded",
                "summary": {"findings": findings},
                "error": None,
            },
        )

        run = get_run(RUN_ID)

    assert run == RunDoc(run_id=RUN_ID, status="succeeded", findings=findings), (
        "The run's status and findings should be parsed."
    )
    assert run.is_finished and run.succeeded, "A succeeded run should be finished."


def test_get_run_raises_on_error_status():
    with requests_mock.mock() as mocker:
        mocker.get(f"{settings.HACKBOT_URL}/runs/{RUN_ID}", status_code=404)

        with pytest.raises(requests.HTTPError):
            get_run(RUN_ID)


@pytest.mark.parametrize(
    "status,is_finished",
    (("pending", False), ("running", False), ("failed", True), ("timed_out", True)),
)
def test_run_doc_is_finished(status: str, is_finished: bool):
    run = RunDoc(run_id=RUN_ID, status=status)

    assert run.is_finished is is_finished, (
        "Only a run in a terminal status should be finished."
    )
    assert not run.succeeded, "Only a succeeded run should have succeeded."


def test_uplift_result_from_json_defaults_missing_fields():
    result = UpliftResult.from_json(
        {"resolved": False, "unresolved": ["README"], "target_branch": "beta"}
    )

    assert result == UpliftResult(resolved=False, unresolved=("README",)), (
        "Missing fields should take their defaults, and unused ones be ignored."
    )


def test_get_artifact_downloads_from_signed_url():
    signed_url = "https://storage.test/changes.patch?signature=abc"

    with requests_mock.mock() as mocker:
        mocker.get(
            f"{settings.HACKBOT_URL}/runs/{RUN_ID}/artifacts/{PATCH_ARTIFACT}",
            json={"url": signed_url},
        )
        mocker.get(signed_url, text="From 1234 Mon Sep 17 00:00:00 2001\n")

        contents = get_artifact(RUN_ID, PATCH_ARTIFACT)

        download_request = mocker.last_request

    assert contents == "From 1234 Mon Sep 17 00:00:00 2001\n", (
        "The artifact contents should come from the signed URL."
    )
    assert "X-API-Key" not in download_request.headers, (
        "The Hackbot API token should not be sent to the signed storage URL."
    )
