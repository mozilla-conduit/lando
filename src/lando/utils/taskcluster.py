import base64
import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import urlsplit

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

UNRESOLVED_TASK_STATES = ("unscheduled", "pending", "running")

# Taskcluster index namespace of the decision task for each Try repository.
TRY_INDEX_PROJECTS = {
    "try": "gecko",
    "try-comm-central": "comm",
}


class TaskclusterNotConfiguredError(Exception):
    """Lando has no Taskcluster credentials."""


class DecisionTaskNotFoundError(Exception):
    """The decision task of a push isn't indexed (yet)."""


def hawk_mac(
    access_token: str,
    ts: int,
    nonce: str,
    method: str,
    resource: str,
    host: str,
    port: int,
    ext: str = "",
) -> str:
    """Return the Hawk MAC of a request, without payload hash."""
    normalized = (
        f"hawk.1.header\n{ts}\n{nonce}\n{method}\n{resource}\n{host}\n{port}\n\n{ext}\n"
    )
    digest = hmac.new(
        access_token.encode(), normalized.encode(), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode()


def hawk_header(client_id: str, access_token: str, method: str, url: str) -> str:
    """Return the `Authorization` header for a Taskcluster API request."""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    resource = parts.path + (f"?{parts.query}" if parts.query else "")
    ts = int(time.time())
    nonce = secrets.token_urlsafe(8)
    mac = hawk_mac(
        access_token, ts, nonce, method, resource, parts.hostname.lower(), port
    )
    return f'Hawk id="{client_id}", ts="{ts}", nonce="{nonce}", mac="{mac}"'


class TaskclusterClient:
    """Minimal client for the Taskcluster APIs needed to cancel a push's tasks."""

    def __init__(
        self,
        root_url: str | None = None,
        client_id: str | None = None,
        access_token: str | None = None,
    ):
        self.root_url = (root_url or settings.TASKCLUSTER_ROOT_URL).rstrip("/")
        self.client_id = client_id or settings.TASKCLUSTER_CLIENT_ID
        self.access_token = access_token or settings.TASKCLUSTER_ACCESS_TOKEN
        self.session = requests.Session()

    @staticmethod
    def is_configured() -> bool:
        return bool(
            settings.TASKCLUSTER_CLIENT_ID and settings.TASKCLUSTER_ACCESS_TOKEN
        )

    def _url(self, service: str, path: str) -> str:
        return f"{self.root_url}/api/{service}/v1/{path}"

    def find_decision_task(self, repo_name: str, revision: str) -> str:
        """Return the decision task ID, which is also the task group ID, of a push."""
        project = TRY_INDEX_PROJECTS.get(repo_name, "gecko")
        namespace = f"{project}.v2.{repo_name}.revision.{revision}.taskgraph.decision"
        response = self.session.get(self._url("index", f"task/{namespace}"), timeout=30)
        if response.status_code == 404:
            raise DecisionTaskNotFoundError(f"No decision task indexed at {namespace}")
        response.raise_for_status()
        return response.json()["taskId"]

    def list_unresolved_tasks(self, task_group_id: str) -> list[str]:
        """Return the IDs of the tasks of the group that haven't resolved yet."""
        task_ids = []
        params = {}
        while True:
            response = self.session.get(
                self._url("queue", f"task-group/{task_group_id}/list"),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            task_ids.extend(
                task["status"]["taskId"]
                for task in data["tasks"]
                if task["status"]["state"] in UNRESOLVED_TASK_STATES
            )
            token = data.get("continuationToken")
            if not token:
                return task_ids
            params = {"continuationToken": token}

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Return `False` if it is past its deadline."""
        if not self.is_configured():
            raise TaskclusterNotConfiguredError("Taskcluster credentials are not set")
        url = self._url("queue", f"task/{task_id}/cancel")
        response = self.session.post(
            url,
            headers={
                "Authorization": hawk_header(
                    self.client_id, self.access_token, "POST", url
                )
            },
            timeout=30,
        )
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True
