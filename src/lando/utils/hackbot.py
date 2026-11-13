"""A client for the Hackbot API, and the shapes of the requests Lando makes to it."""

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Self

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# The Hackbot agent that resolves uplift merge conflicts.
UPLIFT_RESOLVE_AGENT = "uplift-resolve"

# The artifact holding the agent's resolved patch, as a `git format-patch` mbox.
PATCH_ARTIFACT = "changes/changes.patch"

# Run statuses from which a Hackbot run will not change again.
SUCCEEDED_RUN_STATUS = "succeeded"
TERMINAL_RUN_STATUSES = (SUCCEEDED_RUN_STATUS, "failed", "timed_out")


@dataclass(frozen=True)
class UpliftSource:
    """One patch for the uplift agent to apply, as a landed commit or a Phabricator diff."""

    # `git` for a landed commit, or `phabricator` for a revision's diff.
    kind: str

    # The landed commit to cherry-pick, for a `git` source.
    commit: str | None = None

    # The revision to apply, for a `phabricator` source.
    revision_id: int | None = None

    # The diff of `revision_id` to apply, for a `phabricator` source.
    diff_id: int | None = None

    @classmethod
    def from_commit(cls, commit: str) -> Self:
        return cls(kind="git", commit=commit)

    @classmethod
    def from_diff(cls, revision_id: int, diff_id: int) -> Self:
        return cls(kind="phabricator", revision_id=revision_id, diff_id=diff_id)


@dataclass(frozen=True)
class UpliftInputs:
    """The body of a request to start an `uplift-resolve` run."""

    # The stable branch ref to uplift onto, e.g. `beta`.
    target_branch: str

    # The patches to apply onto the branch, in order.
    sources: tuple[UpliftSource, ...]

    # The exact commit to uplift onto, as the branch may move during the run.
    target_commit: str | None = None

    # The originating Bugzilla bug, as extra context for the agent.
    bug_id: int | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the inputs as the JSON Hackbot expects, leaving out unset fields.

        `sources` stays a tuple, which `json` writes as an array.
        """
        return asdict(
            self,
            dict_factory=lambda items: {
                name: value for name, value in items if value is not None
            },
        )


@dataclass(frozen=True)
class RunRef:
    """Hackbot's answer to starting a run: which run is doing the work."""

    # The ID of the run.
    run_id: str

    # The agent running it.
    agent: str

    # The run's status when it was started.
    status: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(run_id=data["run_id"], agent=data["agent"], status=data["status"])


@dataclass(frozen=True)
class UpliftResult:
    """The outcome of an uplift run, as reported in its `summary.findings`."""

    # Whether every source applied and every conflict was resolved.
    resolved: bool = False

    # The agent's own grade: `high`, `medium` or `low`.
    confidence: str | None = None

    # A developer-facing summary of what conflicted and how it was resolved.
    summary: str = ""

    # The conflicts the agent couldn't resolve.
    unresolved: tuple[str, ...] = ()

    # What Hackbot's checks found wrong, which forces `resolved` to `False`.
    verification_failures: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(
            resolved=bool(data.get("resolved", False)),
            confidence=data.get("confidence"),
            summary=data.get("summary") or "",
            unresolved=tuple(data.get("unresolved") or ()),
            verification_failures=tuple(data.get("verification_failures") or ()),
        )


@dataclass(frozen=True)
class RunDoc:
    """A Hackbot run, as returned when polling it."""

    # The ID of the run.
    run_id: str

    # The run's current status.
    status: str

    # Why the run failed, if it did.
    error: str | None = None

    # The agent's raw findings, an `UpliftResult` for uplift runs.
    findings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        summary = data.get("summary") or {}
        return cls(
            run_id=data["run_id"],
            status=data["status"],
            error=data.get("error"),
            findings=summary.get("findings") or {},
        )

    @property
    def is_finished(self) -> bool:
        """Return `True` when the run will not change again."""
        return self.status in TERMINAL_RUN_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCEEDED_RUN_STATUS


def api_request(
    method: str,
    path: str,
    *args,
    headers: dict | None = None,
    **kwargs,
) -> requests.Response:
    """Send an authenticated HTTP request to the Hackbot API.

    All other arguments in `*args` and `**kwargs` are passed through to
    `requests.request`, with a default `timeout` of `settings.HACKBOT_REQUEST_TIMEOUT`.
    """
    url = f"{settings.HACKBOT_URL}/{path}"

    common_headers = {
        "User-Agent": settings.HTTP_USER_AGENT,
        "X-API-Key": settings.HACKBOT_API_TOKEN,
    }
    if headers:
        common_headers.update(headers)

    kwargs.setdefault("timeout", settings.HACKBOT_REQUEST_TIMEOUT)

    response = requests.request(method, url, *args, headers=common_headers, **kwargs)
    response.raise_for_status()
    return response


def start_uplift_resolution(
    inputs: UpliftInputs, on_behalf_of: str, dedupe_key: str
) -> RunRef:
    """Start an `uplift-resolve` run.

    `dedupe_key` makes the call safe to retry: Hackbot returns the existing run
    for a key it has already seen rather than starting a second one.
    """
    logger.debug("Starting a Hackbot uplift resolution run.")
    response = api_request(
        "POST",
        f"agents/{UPLIFT_RESOLVE_AGENT}/runs",
        headers={"X-On-Behalf-Of": on_behalf_of},
        params={"dedupe_key": dedupe_key},
        json=inputs.to_json(),
    )
    return RunRef.from_json(response.json())


def get_run(run_id: str) -> RunDoc:
    """Return the Hackbot run `run_id`."""
    return RunDoc.from_json(api_request("GET", f"runs/{run_id}").json())


def get_artifact(run_id: str, artifact_path: str) -> str:
    """Return the contents of one of a run's artifacts.

    Hackbot hands back a short-lived signed URL rather than the artifact itself,
    so this fetches the URL and then downloads from it straight away.
    """
    logger.debug(f"Fetching a download URL for {artifact_path} of run {run_id}.")
    download_url = api_request(
        "GET", f"runs/{run_id}/artifacts/{artifact_path}"
    ).json()["url"]

    logger.debug(f"Downloading {artifact_path} of run {run_id}.")
    response = requests.get(
        download_url,
        headers={"User-Agent": settings.HTTP_USER_AGENT},
        timeout=settings.HACKBOT_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.text
