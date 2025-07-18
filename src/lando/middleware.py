import cProfile
import logging
import pstats
from collections.abc import Callable
from io import StringIO
from typing import Optional

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import resolve

from lando.main.models import ConfigurationKey, ConfigurationVariable

logger = logging.getLogger(__name__)


class ResponseHeadersMiddleware:
    """Add custom response headers for each request."""

    def __init__(self, get_response: Callable[[WSGIRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: WSGIRequest) -> HttpResponse:
        # NOTE: These headers were ported from both the legacy UI and API.
        # API specific CSP headers should be implemented as part of bug 1927163.

        response = self.get_response(request)

        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"

        csp = [
            "default-src 'self'",
            "base-uri 'none'",
            "font-src 'self'  *.googleapis.com https://code.cdn.mozilla.net",
            "frame-ancestors 'none'",
            "frame-src 'none'",
            "img-src 'self' *.gravatar.com *.googleapis.com",
            "manifest-src 'none'",
            "media-src 'none'",
            "object-src 'none'",
            "script-src 'self' *.googleapis.com",
            "worker-src 'none'",
        ]

        if settings.DEBUG and response.status_code >= 400:
            # `unsafe-inline` is needed for debug pages which have inline CSS.
            csp.append(
                "style-src 'self' 'unsafe-inline' *.googleapis.com https://code.cdn.mozilla.net"
            )
        else:
            csp.append("style-src 'self' *.googleapis.com https://code.cdn.mozilla.net")

        report_uri = settings.CSP_REPORTING_URL

        if report_uri:
            csp.append("report-uri {}".format(report_uri))

        response["Content-Security-Policy"] = "; ".join(csp)

        return response


class MaintenanceModeMiddleware:
    """If maintenance mode is enabled, non-admin requests should be redirected."""

    def __init__(self, get_response: Callable[[WSGIRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: WSGIRequest) -> HttpResponse:
        if request.user.is_authenticated and request.user.is_superuser:
            return self.get_response(request)

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

        maintenance_message = ConfigurationVariable.get(
            ConfigurationKey.MAINTENANCE_MESSAGE,
            "Lando is under maintenance and is temporarily unavailable. Please try again later.",
        )

        if (
            in_maintenance
            and resolve(request.path).namespace not in excepted_namespaces
            and resolve(request.path).url_name not in excepted_url_names
        ):
            return HttpResponse(
                render_to_string(
                    "503.html",
                    {
                        "in_maintenance": True,
                        "maintenance_message": maintenance_message,
                    },
                )
            )

        return self.get_response(request)


class cProfileMiddleware:
    """A middleware to profile requests/responses and return the result.

    To generate a profile report for a request, the following conditions must be met:
    - Request must be sent by an authenticated staff user.
    - The PROFILING_ENABLED configuration variable must be set to True.
    - The "profile" query parameter must be passed in the URL.

    In addition, the following parameters can be passed to customize the report:
    - sort (see https://docs.python.org/3/library/profile.html#pstats.Stats.sort_stats for options).
    """

    @staticmethod
    def _should_profile(request: WSGIRequest) -> bool:
        return (
            ConfigurationVariable.get(ConfigurationKey.PROFILING_ENABLED, False)
            and request.user.is_staff
            and "profile" in request.GET
        )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: WSGIRequest,
        view_func: Callable,
        view_args: tuple,
        view_kwargs: dict,
    ) -> Optional[HttpResponse]:
        """If profile is requested, run cprofile and generate the output in html format."""
        if not self._should_profile(request):
            return

        profiler = cProfile.Profile()
        profiler.runcall(view_func, request, *view_args, **view_kwargs)
        profiler.create_stats()
        out = StringIO()
        stats = pstats.Stats(profiler, stream=out)
        stats.strip_dirs().sort_stats(request.GET.get("sort", "cumtime"))
        stats.print_stats()
        return HttpResponse(f"<pre>{out.getvalue()}</pre>")
