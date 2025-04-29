"""
Tests for the PhabricatorClient
"""

import unittest.mock as mock

import pytest
import requests
import requests_mock

from lando.api.tests.utils import phab_url
from lando.utils.phabricator import PhabricatorAPIException

pytestmark = pytest.mark.usefixtures("docker_env_vars")


def test_ping_success(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    with requests_mock.mock() as m:
        m.post(
            phab_url("conduit.ping"),
            status_code=200,
            json={"result": [], "error_code": None, "error_info": None},
        )
        phab.call_conduit("conduit.ping")
        assert m.called


def test_raise_exception_if_ping_encounters_connection_error(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    with requests_mock.mock() as m:
        # Test with the generic ConnectionError, which is a superclass for
        # other connection error types.
        m.post(phab_url("conduit.ping"), exc=requests.ConnectionError)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit("conduit.ping")
        assert m.called


def test_raise_exception_if_api_ping_times_out(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.post(phab_url("conduit.ping"), exc=requests.Timeout)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit("conduit.ping")
        assert m.called


def test_raise_exception_if_api_returns_error_json_response(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    error_json = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "BOOM",
    }

    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.post(phab_url("conduit.ping"), status_code=500, json=error_json)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit("conduit.ping")
        assert m.called


def test_phabricator_exception(get_phab_client):
    """Ensures that the PhabricatorClient converts JSON errors from Phabricator
    into proper exceptions with the error_code and error_message in tact.
    """
    phab = get_phab_client(api_key="api-key")
    error = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "The value for parameter 'blah' is not valid JSON.",
    }

    with requests_mock.mock() as m:
        m.post(phab_url("differential.query"), status_code=200, json=error)
        with pytest.raises(PhabricatorAPIException) as e_info:
            phab.call_conduit("differential.query", ids=["1"])[0]
        assert e_info.value.error_code == error["error_code"]
        assert e_info.value.error_info == error["error_info"]


@pytest.mark.parametrize(
    "limit",
    [100, 150, None],
)
def test_phabricator__call_conduit_collated(get_phab_client, monkeypatch, limit):
    phab = get_phab_client(api_key="api-key")
    mock_call_conduit = mock.MagicMock()

    first_batch = []
    second_batch = []
    for i in range(100):
        first_batch.append(f"batch-1-{i}")
        second_batch.append(f"batch-2-{i}")

    initial_result = {"data": first_batch.copy(), "cursor": {"after": 1234}}
    second_result = {"data": second_batch.copy(), "cursor": {}}

    mock_call_conduit.side_effect = [initial_result, second_result]
    monkeypatch.setattr(phab, "call_conduit", mock_call_conduit)
    if limit:
        test = phab.call_conduit_collated("conduit.some_method", limit=limit)
    else:
        test = phab.call_conduit_collated("conduit.some_method")

    if limit:
        assert len(test["data"]) == limit
        assert (
            test["data"][limit - 1] == (first_batch + second_batch)[:limit][limit - 1]
        )
    else:
        assert len(test["data"]) == 200
        assert test["data"][:100] == first_batch
        assert test["data"][100:] == second_batch
