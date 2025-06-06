import logging
from json.decoder import JSONDecodeError

import requests

logger = logging.getLogger(__name__)


class TreeStatus:
    """Client for Tree Status API."""

    DEFAULT_URL = "https://treestatus.mozilla-releng.net"

    # A repo is considered open for landing when either of these
    # statuses are present.

    # For the "approval required" status Lando will enforce the appropriate
    # Phabricator group review for approval (`release-managers`) and the hg
    # hook will enforce `a=<reviewer>` is present in the commit message.
    OPEN_STATUSES = {"approval required", "open"}

    def __init__(self, *, url=None, session=None):  # noqa: ANN001
        self.url = url if url is not None else TreeStatus.DEFAULT_URL
        self.url = self.url if self.url[-1] == "/" else self.url + "/"
        self.session = session or self.create_session()

    def is_open(self, tree: str) -> bool:
        if not tree:
            raise ValueError("tree must be a non-empty string")

        try:
            resp = self.get_trees(tree=tree)
        except TreeStatusError as exc:
            if exc.status_code not in (400, 404):
                raise

            # We assume missing trees are open.
            return True

        try:
            return resp["result"]["status"] in TreeStatus.OPEN_STATUSES
        except KeyError as exc:
            raise TreeStatusCommunicationException(
                "Tree status response did not contain expected data"
            ) from exc

    def get_trees(self, tree: str = "") -> dict:
        path = f"trees/{tree}" if tree else "trees"
        return self.request("GET", path)

    @staticmethod
    def create_session() -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": "landoapi.treestatus.TreeStatus/dev"})
        return requests.Session()

    def request(self, method: str, url_path: str, **kwargs) -> dict:
        """Return the response of a request to Tree Status API.

        Args:
            method: HTTP method to use for request.
            url_path: Path to be appended to api url for request.

        Returns:
            JSON decoded response from TreeStatus

        Raises:
            TreeStatusException:
                Base exception class for other exceptions.
            TreeStatusError:
                If the API returns an error response.
            TreeStatusCommunicationException:
                If there is an error communicating with the API.
        """

        try:
            response = self.session.request(method, self.url + url_path, **kwargs)
            data = response.json()
        except requests.RequestException as exc:
            raise TreeStatusCommunicationException(
                "An error occurred when communicating with Tree Status"
            ) from exc
        except JSONDecodeError as exc:
            raise TreeStatusCommunicationException(
                "Tree Status response could not be decoded as JSON"
            ) from exc

        TreeStatusError.raise_if_error(response, data)
        return data

    def ping(self) -> bool:
        """Ping the Tree Status API

        Returns:
            True if ping was successful, False otherwise.
        """
        try:
            self.session.request("HEAD", self.url + "swagger.json")
            return True
        except requests.RequestException:
            return False


class TreeStatusException(Exception):
    """Exception from TreeStatus."""


class TreeStatusCommunicationException(TreeStatusException):
    """Exception when communicating with TreeStatus fails."""


class TreeStatusError(TreeStatusException):
    """Exception when TreeStatus responds with an error."""

    def __init__(self, status_code, data):  # noqa: ANN001
        self.status_code = status_code

        # Error responses should have the RFC 7807 fields at minimum
        # but could include other data, so tack on the response.
        self.response = data

        self.detail = None
        self.instance = None
        self.status = None
        self.title = None
        self.type = None

        try:
            self.detail = data.get("detail")
            self.instance = data.get("instance")
            self.status = data.get("status")
            self.title = data.get("title")
            self.type = data.get("type")
        except AttributeError:
            # Data wasn't a dictionary.
            pass

        super().__init__(self.detail or "")

    @classmethod
    def raise_if_error(cls, response_obj, data):  # noqa: ANN001
        if response_obj.status_code < 400:
            return

        raise cls(response_obj.status_code, data)
