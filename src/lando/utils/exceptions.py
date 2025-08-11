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
