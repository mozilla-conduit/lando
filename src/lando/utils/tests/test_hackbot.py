import pytest
import requests
import requests_mock
from django.conf import settings
from django.test import override_settings

from lando.conftest import HACKBOT_ID_TOKEN
from lando.utils.hackbot import (
    PATCH_ARTIFACT,
    HackbotClient,
    RunDoc,
    RunRef,
    UpliftInputs,
    UpliftResult,
    UpliftSource,
)

RUN_ID = "0b6c1f4e-6c1a-4bd4-9a77-3c1d1f3f4d10"

INPUTS = UpliftInputs(
    target_branch="beta",
    sources=(UpliftSource.from_commit("a" * 40, 3), UpliftSource.from_diff(1, 2)),
)


def test_uplift_inputs_to_json_leaves_out_unset_fields():
    assert INPUTS.to_json() == {
        "target_branch": "beta",
        "sources": (
            {"kind": "git", "commit": "a" * 40, "revision_id": 3},
            {"kind": "phabricator", "revision_id": 1, "diff_id": 2},
        ),
    }, "Unset fields shouldn't be sent, so Hackbot uses its own defaults."


def test_git_source_leaves_out_an_unknown_revision():
    inputs = UpliftInputs(
        target_branch="beta", sources=(UpliftSource.from_commit("a" * 40),)
    )

    assert inputs.to_json()["sources"] == ({"kind": "git", "commit": "a" * 40},), (
        "A `git` source with no revision ID should be sent without one."
    )


def test_start_uplift_resolution_posts_inputs_on_behalf_of_user():
    with requests_mock.mock() as mocker:
        mocker.post(
            f"{settings.HACKBOT_URL}/agents/uplift-resolve/runs",
            json={"run_id": RUN_ID, "agent": "uplift-resolve", "status": "pending"},
            status_code=201,
        )

        run = HackbotClient().start_uplift_resolution(
            INPUTS, "dev@mozilla.com", "lando-key"
        )

        request = mocker.last_request

    assert run == RunRef(run_id=RUN_ID, agent="uplift-resolve", status="pending"), (
        "The new run should be returned."
    )
    assert request.json() == {
        "target_branch": "beta",
        "sources": [
            {"kind": "git", "commit": "a" * 40, "revision_id": 3},
            {"kind": "phabricator", "revision_id": 1, "diff_id": 2},
        ],
    }, "The agent inputs should be the request body, with `sources` as an array."
    assert request.headers["X-On-Behalf-Of"] == "dev@mozilla.com", (
        "The run should be attributed to the requesting user."
    )
    assert request.headers["Authorization"] == f"Bearer {HACKBOT_ID_TOKEN}", (
        "The request should authenticate with a Google ID token."
    )
    assert request.qs == {"dedupe_key": ["lando-key"]}, (
        "The dedupe key should make a retried request reuse its run."
    )


def test_fetch_auth_headers_send_an_id_token_for_the_hackbot_audience(hackbot_id_token):
    headers = HackbotClient().fetch_auth_headers()

    assert headers == {"Authorization": f"Bearer {HACKBOT_ID_TOKEN}"}, (
        "Without `HACKBOT_API_TOKEN`, requests should carry a Google ID token."
    )
    assert hackbot_id_token.call_args.args[1] == settings.HACKBOT_OIDC_AUDIENCE, (
        "The ID token should be minted for `HACKBOT_OIDC_AUDIENCE`."
    )


def test_fetch_auth_headers_prefer_the_api_key_when_set(hackbot_id_token):
    with override_settings(HACKBOT_API_TOKEN="hackbot-api-key"):
        headers = HackbotClient().fetch_auth_headers()

    assert headers == {"X-API-Key": "hackbot-api-key"}, (
        "With `HACKBOT_API_TOKEN` set, requests should send it as `X-API-Key`."
    )
    assert not hackbot_id_token.called, (
        "No ID token should be fetched when an API key is configured."
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

        run = HackbotClient().get_run(RUN_ID)

    assert run == RunDoc(run_id=RUN_ID, status="succeeded", findings=findings), (
        "The run's status and findings should be parsed."
    )
    assert run.is_finished and run.succeeded, "A succeeded run should be finished."


def test_get_run_raises_on_error_status():
    with requests_mock.mock() as mocker:
        mocker.get(f"{settings.HACKBOT_URL}/runs/{RUN_ID}", status_code=404)

        with pytest.raises(requests.HTTPError):
            HackbotClient().get_run(RUN_ID)


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

        contents = HackbotClient().get_artifact(RUN_ID, PATCH_ARTIFACT)

        download_request = mocker.last_request

    assert contents == "From 1234 Mon Sep 17 00:00:00 2001\n", (
        "The artifact contents should come from the signed URL."
    )
    assert "Authorization" not in download_request.headers, (
        "The Hackbot credentials should not be sent to the signed storage URL."
    )


def test_client_sends_requests_to_its_own_url():
    with requests_mock.mock() as mocker:
        mocker.get(
            f"https://hackbot.example/runs/{RUN_ID}",
            json={"run_id": RUN_ID, "status": "running"},
        )

        run = HackbotClient(url="https://hackbot.example").get_run(RUN_ID)

    assert run.run_id == RUN_ID, (
        "A client built with a `url` should send its requests there, "
        "not to `HACKBOT_URL`."
    )
