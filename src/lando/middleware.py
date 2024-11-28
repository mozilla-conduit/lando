import logging
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import resolve

from lando.main.models import ConfigurationKey, ConfigurationVariable

logger = logging.getLogger(__name__)


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
            "script-src 'self' *.googleapis.com",
            "img-src 'self' *.gravatar.com *.googleapis.com",
            "manifest-src 'none'",
            "media-src 'none'",
            "object-src 'none'",
            "worker-src 'none'",
        ]

        if settings.DEBUG and response.status_code >= 400:
            # This is needed for debug pages which have inline CSS.
            csp.append("style-src 'self' 'unsafe-inline' *.googleapis.com")
        else:
            csp.append("style-src 'self' *.googleapis.com")

        report_uri = settings.CSP_REPORTING_URL

        if report_uri:
            csp.append("report-uri {}".format(report_uri))

        response["Content-Security-Policy"] = "; ".join(csp)

        return response


class MaintenanceModeMiddleware:
    """If maintenance mode is enabled, non-admin requests should be redirected."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        excepted_namespaces = (
            "dockerflow",
            "admin",
        )

        excepted_url_names = (
            "oidc_logout",
            "oidc_authentication_init",
            "oidc_authentication_callback",
        )

        in_maintenance = ConfigurationVariable.get(
            ConfigurationKey.API_IN_MAINTENANCE, False
        )

        if (
            in_maintenance
            and resolve(request.path).namespace not in excepted_namespaces
            and resolve(request.path).url_name not in excepted_url_names
        ):
            return HttpResponse(render_to_string("503.html", {"in_maintenance": True}))

        return self.get_response(request)
