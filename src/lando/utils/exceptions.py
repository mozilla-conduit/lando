from django.core.exceptions import PermissionDenied
from django.core.handlers.wsgi import WSGIRequest
from ninja import Schema
from ninja.responses import Response


class ProblemDetail(Schema):
    """RFC 7807-style JSON response on error."""

    title: str
    status: int
    detail: str
    type: str

    def __init__(self, **kwargs):
        if not kwargs.get("type"):
            match kwargs.get("status"):
                case 400:
                    kwargs["type"] = (
                        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400"
                    )
                case 403:
                    kwargs["type"] = (
                        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403"
                    )
                case 404:
                    kwargs["type"] = (
                        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404"
                    )
                case _:
                    kwargs["type"] = "about:blank"
        super().__init__(**kwargs)


class ProblemException(Exception):
    """Exception thrown when a ProblemDetail should be returned."""

    def __init__(
        self,
        *,
        type: str | None = None,
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
        super().__init__(f"{title}: {detail}")

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
        )


class ForbiddenProblemException(ProblemException):
    """`ProblemException` subclass for `403 Forbidden` errors."""

    def __init__(self, title: str, detail: str):
        super().__init__(
            title=title,
            detail=detail,
            status=403,
        )

    @staticmethod
    def from_permission_denied(exc: PermissionDenied) -> "ForbiddenProblemException":
        """Convert a Django PermissionDenied to a ForbiddenProblemException."""
        return ForbiddenProblemException(title="Forbidden", detail=str(exc))


class NotFoundProblemException(ProblemException):
    """`ProblemException` subclass for `404 Not Found` errors."""

    def __init__(self, title: str, detail: str):
        super().__init__(
            title=title,
            detail=detail,
            status=404,
        )


def problem_exception_handler(request: WSGIRequest, exc: ProblemException) -> Response:
    """Convert a thrown `ProblemException` to a response.

    To install for your API, use the following syntax:

        api = NinjaAPI(...)
        api.exception_handler(ProblemException)(problem_exception_handler)
    """
    return Response(
        exc.to_response(),
        status=exc.status_code,
        content_type="application/problem+json",
    )
