from typing import Optional

from ninja import Schema
from pydantic import Field


class ProblemDetail(Schema):
    """RFC 7807-style JSON response on error."""

    title: str
    status: int
    detail: str
    type: Optional[str] = Field(default="about:blank")


class ProblemException(Exception):
    """Exception thrown when a ProblemDetail should be returned."""

    def __init__(
        self,
        *,
        type: str = "about:blank",
        title: str,
        detail: str,
        status: int = 400,
    ):
        self.problem = ProblemDetail(
            type=type,
            title=title,
            status=status,
            detail=detail,
        )

        # Needed by Ninja exception handler.
        self.status_code = status

    def to_response(self) -> dict:
        """Convert the `ProblemException` into a JSON-serializable dict."""
        return self.problem.dict()


class BadRequestProblemException(ProblemException):
    """`ProblemException` subclass for `400 Bad Request` errors."""

    def __init__(self, title: str, detail: str):
        super().__init__(
            title=title,
            detail=detail,
            status=400,
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )


class NotFoundProblemException(ProblemException):
    """`ProblemException` subclass for `404 Not Found` errors."""

    def __init__(self, title: str, detail: str):
        super().__init__(
            title=title,
            detail=detail,
            status=404,
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )
