from unittest import mock

import pytest

from lando.utils.phabricator import (
    PhabricatorAPIException,
    PhabricatorClient,
    PhabricatorCommunicationException,
)
from lando.utils.tasks import admin_remove_phab_project, request_ai_change_approval


def test_admin_remove_phab_project_succeeds(phabdouble, app):
    p = phabdouble.project("test-project")
    r = phabdouble.revision(projects=[p])
    admin_remove_phab_project(r["phid"], p["phid"])


def test_admin_remove_phab_project_throws_exception_for_missing_revision(
    phabdouble, app
):
    p = phabdouble.project("test-project")
    with pytest.raises(PhabricatorAPIException) as excinfo:
        admin_remove_phab_project("PHID-DREV-NOTAREALPHID", p["phid"])

    # Make sure that we haven't thrown a PhabricatorCommunicationException
    # which would be a transient error. The exception should be a normal
    # PhabricatorAPIException.
    assert isinstance(excinfo.value, PhabricatorAPIException)
    assert not isinstance(excinfo.value, PhabricatorCommunicationException)
    assert "does not identify a valid object" in excinfo.value.error_info


def test_request_ai_change_approval_requests_as_lando(monkeypatch, settings):
    settings.PHABRICATOR_ADMIN_API_KEY = "api-lando-admin-key"
    phabricator_client = mock.MagicMock()
    monkeypatch.setattr("lando.utils.tasks.PhabricatorClient", phabricator_client)
    request = {"kind": "merge-conflict", "changeDiffID": 51, "baseDiffID": 50}

    request_ai_change_approval(1234, request)

    assert phabricator_client.call_args.args[1] == "api-lando-admin-key", (
        "The request should be sent with Lando's own API key."
    )
    phabricator_client.return_value.call_conduit.assert_called_once_with(
        "differential.revision.edit",
        objectIdentifier=1234,
        transactions=[{"type": "ai-change.request", "value": request}],
    )


def test_request_ai_change_approval_uses_the_active_diff_without_a_change_diff(
    phabdouble, app
):
    revision = phabdouble.revision()
    active_diff = phabdouble.diff(revision=revision)
    request = {"kind": "merge-conflict", "summary": None}

    with mock.patch.object(
        PhabricatorClient, "call_conduit", side_effect=phabdouble.call_conduit
    ) as call_conduit:
        request_ai_change_approval(revision["id"], request)

    edit_call = call_conduit.call_args
    assert edit_call.args[0] == "differential.revision.edit", (
        "The approval should be requested after looking up the active diff."
    )
    assert edit_call.kwargs["transactions"] == [
        {
            "type": "ai-change.request",
            "value": {**request, "changeDiffID": active_diff["id"]},
        }
    ], "The request should be made on the revision's active diff."
