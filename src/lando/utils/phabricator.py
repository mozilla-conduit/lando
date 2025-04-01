from __future__ import annotations

import json
import logging
from datetime import (
    datetime,
    timezone,
)
from enum import (
    Enum,
    unique,
)
from json.decoder import JSONDecodeError
from typing import (
    Any,
    Iterable,
    Optional,
)

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@unique
class PhabricatorRevisionStatus(Enum):
    """Enumeration of statuses a revision may have.

    These statuses were exhaustive at the time of creation, but
    Phabricator may add statuses in the future (such as the DRAFT
    status that was recently added).
    """

    ABANDONED = "abandoned"
    ACCEPTED = "accepted"
    CHANGES_PLANNED = "changes-planned"
    PUBLISHED = "published"
    NEEDS_REVIEW = "needs-review"
    NEEDS_REVISION = "needs-revision"
    DRAFT = "draft"
    UNEXPECTED_STATUS = None

    @classmethod
    def from_status(cls, value: str) -> PhabricatorRevisionStatus:
        try:
            return cls(value)
        except ValueError:
            pass

        return cls.UNEXPECTED_STATUS

    @classmethod
    def meta(cls) -> dict:
        return {
            cls.ABANDONED: {
                "name": "Abandoned",
                "closed": True,
                "color.ansi": None,
                "deprecated_id": "4",
            },
            cls.ACCEPTED: {
                "name": "Accepted",
                "closed": False,
                "color.ansi": "green",
                "deprecated_id": "2",
            },
            cls.CHANGES_PLANNED: {
                "name": "Changes Planned",
                "closed": False,
                "color.ansi": "red",
                "deprecated_id": "5",
            },
            cls.PUBLISHED: {
                "name": "Closed",
                "closed": True,
                "color.ansi": "cyan",
                "deprecated_id": "3",
            },
            cls.NEEDS_REVIEW: {
                "name": "Needs Review",
                "closed": False,
                "color.ansi": "magenta",
                "deprecated_id": "0",
            },
            cls.NEEDS_REVISION: {
                "name": "Needs Revision",
                "closed": False,
                "color.ansi": "red",
                "deprecated_id": "1",
            },
            cls.DRAFT: {
                "name": "Draft",
                "closed": False,
                "color.ansi": None,
                "deprecated_id": "0",
            },
        }

    @property
    def deprecated_id(self) -> str:
        return self.meta().get(self, {}).get("deprecated_id", "")

    @property
    def output_name(self) -> str:
        return self.meta().get(self, {}).get("name", "")

    @property
    def closed(self) -> bool:
        return self.meta().get(self, {}).get("closed", False)

    @property
    def color(self) -> Optional[str]:
        return self.meta().get(self, {}).get("color.ansi")


@unique
class ReviewerStatus(Enum):
    """Enumeration of statuses a reviewer may have.

    These statuses were exhaustive at the time of creation, but
    Phabricator may add statuses in the future.
    """

    ADDED = "added"
    ACCEPTED = "accepted"
    BLOCKING = "blocking"
    REJECTED = "rejected"
    RESIGNED = "resigned"
    UNEXPECTED_STATUS = None

    @classmethod
    def from_status(cls, value: str) -> ReviewerStatus:
        try:
            return cls(value)
        except ValueError:
            pass

        return cls.UNEXPECTED_STATUS

    @property
    def diff_specific(self) -> bool:
        return {
            self.ADDED: False,
            self.ACCEPTED: True,
            self.BLOCKING: False,
            self.REJECTED: True,
            self.RESIGNED: False,
            self.UNEXPECTED_STATUS: False,
        }.get(self, False)


class PhabricatorClient:
    """A class to interface with Phabricator's Conduit API.

    All request methods in this class will throw a PhabricatorAPIException if
    Phabricator returns an error response. If there is an actual problem with
    the request to the server or decoding the JSON response, this class will
    bubble up the exception, as a PhabricatorAPIException caused by the
    underlying exception.
    """

    def __init__(
        self, url: str, api_token: str, *, session: Optional[requests.Session] = None
    ):
        self.url_base = url
        self.api_url = url + "api/" if url[-1] == "/" else url + "/api/"
        self.api_token = api_token
        self.session = session or self.create_session()

    def call_conduit(self, method: str, **kwargs) -> Any:  # noqa: ANN401
        """Return the result of an RPC call to a conduit method.

        Args:
            **kwargs: Every method parameter is passed as a keyword argument.

        Returns:
            The 'result' key of the conduit method's response or None if
            the 'result' key doesn't exist.

        Raises:
            PhabricatorAPIException:
                if conduit returns an error response.
            requests.exceptions.RequestException:
                if there is a request exception while communicating
                with the conduit API.
        """
        if "__conduit__" not in kwargs:
            kwargs["__conduit__"] = {"token": self.api_token}

        data = {"output": "json", "params": json.dumps(kwargs)}

        extra_data = {
            "params": kwargs.copy(),
            "method": method,
            "api_url": self.api_url,
        }
        del extra_data["params"]["__conduit__"]  # Sanitize the api token.
        logger.debug("call to conduit", extra=extra_data)

        try:
            response = self.session.post(self.api_url + method, data=data).json()
        except requests.RequestException as exc:
            raise PhabricatorCommunicationException(
                "An error occurred when communicating with Phabricator"
            ) from exc
        except JSONDecodeError as exc:
            raise PhabricatorCommunicationException(
                "Phabricator response could not be decoded as JSON"
            ) from exc

        PhabricatorAPIException.raise_if_error(response)
        return response.get("result")

    @staticmethod
    def create_session() -> requests.Session:
        session = requests.Session()
        headers = {"User-Agent": settings.HTTP_USER_AGENT}
        session.headers.update(headers)
        return session

    @classmethod
    def single(
        cls,
        result: Any,  # noqa: ANN401
        *subkeys: Iterable[int | str],
        none_when_empty: bool = False,  # noqa: ANN401
    ) -> Optional[Any]:  # noqa: ANN401
        """Return the first item of a phabricator result.

        Args:
            cls: class this method is called on.
            result: Data from the result key of a Phabricator API response.
            *subkeys: An iterable of subkeys which the list of items is
                present under. A common value would be ['data'] for standard
                search conduit methods.
            none_when_empty: `None` is returned if the result is empty if
                `none_when_empty` is True.

        Returns:
            The first result in the provided data. If `none_when_empty` is
            `True`, `None` will be returned if the result is empty.

        Raises:
            PhabricatorCommunicationException:
                If there is more or less than a single item.
        """
        if subkeys:
            result = cls.expect(result, *subkeys)

        if len(result) > 1 or (not result and not none_when_empty):
            raise PhabricatorCommunicationException(
                "Phabricator responded with unexpected data: %s" % result
            )

        return result[0] if result else None

    @staticmethod
    def expect(result: Any, *args) -> Any:  # noqa: ANN401
        """Return data from a phabricator result.

        Args:
            result: Data from the result key of a Phabricator API response.
            *args: a path of keys into result which should and must
                exist. If data is missing or malformed when attempting
                to access the specific path an exception is raised.

        Returns:
            The data which exists at the path specified by args.

        Raises:
            PhabricatorCommunicationException:
                If the data is malformed or missing.
        """
        try:
            for k in args:
                result = result[k]
        except (IndexError, KeyError, ValueError, TypeError) as exc:
            raise PhabricatorCommunicationException(
                "Phabricator responded with unexpected data"
            ) from exc

        return result

    @staticmethod
    def to_datetime(timestamp: int | str) -> datetime:
        """Return a datetime corresponding to a Phabricator timestamp.

        Args:
            timestamp: An integer, or integer string, timestamp from
            Phabricator which is the epoch in seconds UTC.

        Returns:
            A python datetime object for the same time.
        """
        return datetime.fromtimestamp(int(timestamp), timezone.utc)

    def verify_api_token(self) -> bool:
        """Verifies that the api token is valid.

        Returns False if Phabricator returns an error code when checking this
        api token. Returns True if no errors are found.
        """
        try:
            self.call_conduit("user.whoami")
        except PhabricatorAPIException:
            return False
        return True


class PhabricatorAPIException(Exception):
    """Exception to be raised when Phabricator returns an error response."""

    def __init__(
        self, *args, error_code: Optional[str] = None, error_info: Optional[str] = None
    ):
        super().__init__(*args)
        self.error_code = error_code
        self.error_info = error_info

    @classmethod
    def raise_if_error(cls, response_body: dict):
        """Raise a PhabricatorAPIException if response_body was an error."""
        if response_body["error_code"]:
            raise cls(
                response_body.get("error_info"),
                error_code=response_body.get("error_code"),
                error_info=response_body.get("error_info"),
            )


class PhabricatorCommunicationException(PhabricatorAPIException):
    """Exception when communicating with Phabricator fails."""


def result_list_to_phid_dict(
    result_list: list[dict], *, phid_key: str = "phid"
) -> dict[str, dict]:
    """Return a dictionary mapping phid to items from a result list.

    Args:
        result_list: A list of result items from phabricator which
            contain a phid in the key specified by `phid_key`
        phid_key: The key to access the phid from each item.
    """
    result = {}
    for i in result_list:
        phid = PhabricatorClient.expect(i, phid_key)
        if phid in result:
            raise PhabricatorCommunicationException(
                "Phabricator responded with unexpected data"
            )

        result[phid] = i

    return result


def get_phabricator_client(
    privileged: Optional[bool] = False, api_key: Optional[str] = None
) -> PhabricatorClient:
    """Return an initialized PhabricatorClient object with relevant API key."""
    api_key = (
        api_key or settings.PHABRICATOR_ADMIN_API_KEY
        if privileged
        else settings.PHABRICATOR_UNPRIVILEGED_API_KEY
    )
    phab = PhabricatorClient(
        settings.PHABRICATOR_URL,
        api_key,
    )
    return phab
