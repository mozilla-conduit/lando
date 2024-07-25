import requests
from django.conf import settings


def bmo_uplift_endpoint() -> str:
    """Returns the BMO uplift endpoint url for bugs."""
    return f"{settings.BUGZILLA_URL}/rest/lando/uplift"


def bmo_default_headers() -> dict[str, str]:
    """Returns a `dict` containing the default REST API headers."""
    return {
        "User-Agent": "Lando-API",
        "X-Bugzilla-API-Key": settings.BUGZILLA_API_KEY,
    }


def get_bug(params: dict) -> requests.Response:
    """Retrieve bug information from the BMO REST API endpoint."""
    resp_get = requests.get(
        bmo_uplift_endpoint(), headers=bmo_default_headers(), params=params
    )
    resp_get.raise_for_status()

    return resp_get


def update_bug(json: dict) -> requests.Response:
    """Update a BMO bug."""
    if "ids" not in json or not json["ids"]:
        raise ValueError("Need bug values to be able to update!")

    resp_put = requests.put(
        bmo_uplift_endpoint(), headers=bmo_default_headers(), json=json
    )
    resp_put.raise_for_status()

    return resp_put
