import logging
from collections.abc import Iterable
from typing import Optional

import requests
from django.conf import settings

from lando.utils.cache import cache_method

logger = logging.getLogger(__name__)

SECURITY_KEYWORDS = ("sec-critical", "sec-high")
UNSET_STATUS_FLAG_VALUES = ("", "---")


class BugFetchError(Exception):
    """Raised when Lando cannot retrieve bug data from BMO.

    Covers a connection failure, a 4xx/5xx response, and a malformed payload, so
    callers can degrade the security status-flag checks to an acknowledgeable
    warning with a single `except` rather than testing for a `None` return.
    """


def security_keyword(bug: dict) -> str | None:
    """Return the bug's sec-critical/sec-high keyword, or `None` if it has neither.

    When both are somehow present, `sec-critical` takes precedence.
    """
    keywords = set(bug.get("keywords", []))
    for keyword in SECURITY_KEYWORDS:
        if keyword in keywords:
            return keyword
    return None


def unset_status_flags(bug: dict, prefix: str) -> list[str]:
    """Return the sorted names of unset status flags matching `prefix` on a bug.

    `prefix` is the target repo's configured status-flag prefix (e.g.
    `cf_status_firefox`).
    """
    return sorted(
        name
        for name, value in bug.items()
        if name.startswith(prefix)
        and (value is None or value in UNSET_STATUS_FLAG_VALUES)
    )


def missing_status_flags_message(
    bug_id: int, keyword: str, missing_flags: list[str]
) -> str:
    """Return the blocker message for a security bug missing status flags.

    Shared by the Phabricator and GitHub security status-flag checks so the two
    flows cannot drift apart.
    """
    return (
        f"Bug {bug_id} is marked {keyword} but is missing status flags: "
        f"{', '.join(missing_flags)}. Set the status flag (e.g. affected, "
        "unaffected, or disabled) for every affected branch in Bugzilla, then "
        "reload this page."
    )


def unverified_status_flags_message(bug_ids: Iterable[int]) -> str:
    """Return the warning message when status flags could not be verified.

    Accepts one or more bug ids and produces a single message. Shared by the
    Phabricator and GitHub security status-flag checks.
    """
    ids = sorted(bug_ids)
    if len(ids) == 1:
        subject, pronoun = f"bug {ids[0]}", "its"
    else:
        subject = "bugs " + ", ".join(str(bug_id) for bug_id in ids)
        pronoun = "their"
    return (
        f"Lando could not verify the status flags on {subject} in Bugzilla. "
        f"Please ensure {pronoun} status flags are set before landing."
    )


def api_request(
    method: str,
    path: str,
    *args,
    use_api_key: bool = False,
    headers: Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    """Send an HTTP request to the BMO REST API.

    `method` is the HTTP method to use, ie `GET`, `POST`, etc.
    `path` is the REST API endpoint to send the request to.
    `authenticated` indicates if the privileged Lando Automation API key should be
      used.
    `headers` is the set of HTTP headers to pass to the request.

    All other arguments in *args and **kwargs are passed through to `requests.request`.
    A default `timeout` of `settings.BMO_REQUEST_TIMEOUT` is applied so a hung
    connection can't tie up a web worker indefinitely; callers may override it by
    passing `timeout`.
    """
    url = f"{settings.BUGZILLA_URL}/rest/{path}"

    common_headers = {
        "User-Agent": settings.HTTP_USER_AGENT,
    }
    if headers:
        common_headers.update(headers)

    if use_api_key:
        common_headers["X-Bugzilla-API-Key"] = settings.BUGZILLA_API_KEY

    kwargs.setdefault("timeout", settings.BMO_REQUEST_TIMEOUT)

    return requests.request(method, url, *args, headers=common_headers, **kwargs)


def search_bugs(bug_ids: set[int]) -> set[int]:
    """Search for bugs with given IDs on BMO."""
    params = {
        "id": ",".join(str(bug) for bug in sorted(bug_ids)),
        "include_fields": "id",
    }

    resp = api_request(
        "GET",
        "bug",
        params=params,
    )

    bugs = resp.json()["bugs"]

    return {int(bug["id"]) for bug in bugs}


def get_status_code_for_bug(bug_id: int) -> int:
    """Given a bug ID, get the status code returned from BMO when attempting to access the bug."""
    try:
        resp = api_request("GET", f"bug/{bug_id}")
        code = resp.status_code
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code

    return code


def uplift_get_bug(params: dict) -> dict:
    """Retrieve bug information from the Lando Uplift Automation endpoint."""
    resp_get = api_request("GET", "lando/uplift", use_api_key=True, params=params)
    resp_get.raise_for_status()

    return resp_get.json()


def uplift_update_bug(json: dict) -> requests.Response:
    """Update a BMO bug via the Lando Uplift Automation endpoint."""
    if "ids" not in json or not json["ids"]:
        raise ValueError("Need bug values to be able to update!")

    resp_put = api_request("PUT", "lando/uplift", use_api_key=True, json=json)
    resp_put.raise_for_status()

    return resp_put


def _fetch_bugs_cache_key(bug_ids: set[int]) -> str:
    return "bmo_status_flags_" + ",".join(str(bug) for bug in sorted(bug_ids))


@cache_method(_fetch_bugs_cache_key, timeout=settings.BMO_BUGS_CACHE_TIMEOUT)
def fetch_bugs(bug_ids: set[int]) -> dict[int, dict]:
    """Fetch BMO bug data for the given bug ids, keyed by bug id.

    Returns an empty dict when `bug_ids` is empty and the id->bug mapping on
    success. Raises `BugFetchError` if the fetch failed, so callers can degrade
    the security status-flag checks to an acknowledgeable warning rather than
    crashing:

    - 4xx responses (e.g. an expired or misconfigured ``BUGZILLA_API_KEY``) get a
      distinct log message so the misconfiguration is identifiable, rather than
      looking like a generic outage.
    - Connection errors and 5xx responses are transient outages.
    - A malformed payload (missing ``bugs`` key, non-integer id) is also caught so
      it cannot crash the caller.

    `cache_method` briefly caches successful results (see
    `settings.BMO_BUGS_CACHE_TIMEOUT`) so the stack-page and landing-request paths
    don't each hit BMO; it does not cache a raised `BugFetchError`, so a transient
    outage doesn't stick.
    """
    if not bug_ids:
        return {}

    params = {"id": ",".join(str(bug) for bug in sorted(bug_ids))}
    try:
        bugs = uplift_get_bug(params)["bugs"]
        return {int(bug["id"]): bug for bug in bugs}
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None and 400 <= status_code < 500:
            logger.warning(
                "BMO rejected the Lando status-flag request with HTTP %s; check "
                "BUGZILLA_API_KEY. Security status-flag checks will degrade to a "
                "warning until this is resolved.",
                status_code,
            )
        else:
            logger.warning("BMO returned an error fetching bug status flags.")
        raise BugFetchError from exc
    except requests.exceptions.RequestException as exc:
        logger.warning("Failed to reach BMO for bug status flags.")
        raise BugFetchError from exc
    except (KeyError, TypeError, ValueError) as exc:
        logger.exception("BMO returned a malformed bug status-flag payload.")
        raise BugFetchError from exc
