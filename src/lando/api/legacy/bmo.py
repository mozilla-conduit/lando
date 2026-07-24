from typing import Optional

import requests
from django.conf import settings

SECURITY_KEYWORDS = ("sec-critical", "sec-high")
STATUS_FLAG_PREFIX = "cf_status_firefox"
UNSET_STATUS_FLAG_VALUES = ("", "---")


def security_keyword(bug: dict) -> str | None:
    """Return the bug's sec-critical/sec-high keyword, or `None` if it has neither.
    When both are somehow present, `sec-critical` takes precedence.
    """
    keywords = set(bug.get("keywords", []))
    for keyword in SECURITY_KEYWORDS:
        if keyword in keywords:
            return keyword
    return None


def is_security_bug(bug: dict) -> bool:
    """Return whether a BMO bug dict carries a sec-critical/sec-high keyword."""
    return security_keyword(bug) is not None


def unset_status_flags(bug: dict) -> list[str]:
    """Return the sorted names of unset Firefox status flags on a BMO bug dict."""
    return sorted(
        name
        for name, value in bug.items()
        if name.startswith(STATUS_FLAG_PREFIX)
        and (value is None or value in UNSET_STATUS_FLAG_VALUES)
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
    """
    url = f"{settings.BUGZILLA_URL}/rest/{path}"

    common_headers = {
        "User-Agent": settings.HTTP_USER_AGENT,
    }
    if headers:
        common_headers.update(headers)

    if use_api_key:
        common_headers["X-Bugzilla-API-Key"] = settings.BUGZILLA_API_KEY

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
