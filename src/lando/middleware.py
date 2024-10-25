from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class ResponseHeadersMiddleware:
    """Add custom response headers for each request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # NOTE: These headers were ported from both the legacy UI and API.
        # API specific CSP headers should be implemented as part of bug 1927163.

        response = self.get_response(request)

        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"

        csp = [
            "default-src 'self'",
            "base-uri 'none'",
            "font-src 'self' https://code.cdn.mozilla.net",
            "frame-ancestors 'none'",
            "frame-src 'none'",
            "img-src 'self' *.cloudfront.net *.gravatar.com *.googleusercontent.com",
            "manifest-src 'none'",
            "media-src 'none'",
            "object-src 'none'",
            "style-src 'self' https://code.cdn.mozilla.net",
            "worker-src 'none'",
        ]

        report_uri = settings.CSP_REPORTING_URL

        if report_uri:
            csp.append("report-uri {}".format(report_uri))

        response["Content-Security-Policy"] = "; ".join(csp)

        return response
