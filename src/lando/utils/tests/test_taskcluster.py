import re

import pytest
import requests

from lando.utils.taskcluster import (
    DecisionTaskNotFoundError,
    TaskclusterClient,
    TaskclusterNotConfiguredError,
    hawk_header,
    hawk_mac,
)
from lando.utils.tasks import cancel_try_push_tasks

ROOT_URL = "https://tc.test"


@pytest.fixture
def tc_settings(settings):
    settings.TASKCLUSTER_ROOT_URL = ROOT_URL
    settings.TASKCLUSTER_CLIENT_ID = "project/lando/cancel"
    settings.TASKCLUSTER_ACCESS_TOKEN = "secret"
    return settings


def test_hawk_mac_matches_spec_vector():
    # Test vector from the Hawk specification.
    mac = hawk_mac(
        "werxhqb98rpaxn39848xrunpaw3489ruxnpa98w4rxn",
        1353832234,
        "j4h3g2",
        "GET",
        "/resource/1?b=1&a=2",
        "example.com",
        8000,
        "some-app-ext-data",
    )
    assert mac == "6R4rV5iE+NPoym+WwjeHzjAGXUtLNIxmo1vpMofpLAE="


def test_hawk_header_format():
    header = hawk_header("client", "token", "POST", f"{ROOT_URL}/api/queue/v1/x")
    assert header.startswith('Hawk id="client", ts="')
    assert 'nonce="' in header
    assert 'mac="' in header


def test_find_decision_task(tc_settings, requests_mock):
    requests_mock.get(
        f"{ROOT_URL}/api/index/v1/task/gecko.v2.try.revision.{'a' * 40}.taskgraph.decision",
        json={"taskId": "decision"},
    )
    assert TaskclusterClient().find_decision_task("try", "a" * 40) == "decision"


def test_find_decision_task_comm(tc_settings, requests_mock):
    requests_mock.get(
        f"{ROOT_URL}/api/index/v1/task/comm.v2.try-comm-central.revision.{'a' * 40}.taskgraph.decision",
        json={"taskId": "decision"},
    )
    assert (
        TaskclusterClient().find_decision_task("try-comm-central", "a" * 40)
        == "decision"
    )


def test_find_decision_task_not_indexed(tc_settings, requests_mock):
    requests_mock.get(re.compile(f"{ROOT_URL}/api/index/v1/task/.*"), status_code=404)
    with pytest.raises(DecisionTaskNotFoundError):
        TaskclusterClient().find_decision_task("try", "a" * 40)


def _status(task_id: str, state: str) -> dict:
    return {"status": {"taskId": task_id, "state": state}}


def test_list_unresolved_tasks_follows_continuation(tc_settings, requests_mock):
    url = f"{ROOT_URL}/api/queue/v1/task-group/group/list"
    requests_mock.get(
        url,
        [
            {
                "json": {
                    "tasks": [
                        _status("t1", "completed"),
                        _status("t2", "running"),
                    ],
                    "continuationToken": "next",
                }
            },
            {
                "json": {
                    "tasks": [
                        _status("t3", "pending"),
                        _status("t4", "unscheduled"),
                        _status("t5", "exception"),
                    ]
                }
            },
        ],
    )

    assert TaskclusterClient().list_unresolved_tasks("group") == ["t2", "t3", "t4"]
    assert requests_mock.request_history[1].qs == {"continuationtoken": ["next"]}


def test_cancel_task(tc_settings, requests_mock):
    requests_mock.post(f"{ROOT_URL}/api/queue/v1/task/t1/cancel", json={})
    requests_mock.post(f"{ROOT_URL}/api/queue/v1/task/t2/cancel", status_code=409)
    requests_mock.post(f"{ROOT_URL}/api/queue/v1/task/t3/cancel", status_code=403)

    tc = TaskclusterClient()
    assert tc.cancel_task("t1") is True
    assert requests_mock.last_request.headers["Authorization"].startswith(
        'Hawk id="project/lando/cancel"'
    )
    assert tc.cancel_task("t2") is False
    with pytest.raises(requests.HTTPError):
        tc.cancel_task("t3")


def test_cancel_task_not_configured(settings):
    settings.TASKCLUSTER_CLIENT_ID = ""
    settings.TASKCLUSTER_ACCESS_TOKEN = ""
    with pytest.raises(TaskclusterNotConfiguredError):
        TaskclusterClient().cancel_task("t1")


def test_cancel_try_push_tasks(tc_settings, requests_mock):
    revision = "a" * 40
    requests_mock.get(
        f"{ROOT_URL}/api/index/v1/task/gecko.v2.try.revision.{revision}.taskgraph.decision",
        json={"taskId": "group"},
    )
    requests_mock.get(
        f"{ROOT_URL}/api/queue/v1/task-group/group/list",
        json={
            "tasks": [
                _status("group", "completed"),
                _status("t1", "running"),
                _status("t2", "pending"),
            ]
        },
    )
    cancel_t1 = requests_mock.post(f"{ROOT_URL}/api/queue/v1/task/t1/cancel", json={})
    cancel_t2 = requests_mock.post(
        f"{ROOT_URL}/api/queue/v1/task/t2/cancel", status_code=409
    )

    cancel_try_push_tasks("try", revision, "user@example.org")

    assert cancel_t1.called_once
    assert cancel_t2.called_once
