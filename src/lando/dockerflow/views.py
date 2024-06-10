from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views import View

from lando.dockerflow.decorators import disable_caching, log_request


class VersionView(View):
    """
    This view handles the version information of Lando.

    It returns a JSON response containing the version information.
    """

    @disable_caching
    @log_request
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        try:
            from lando.version import version

            data = {
                "version": version,
            }
            status_code = 200
        except ImportError:
            data = {"error": "Service Unavailable"}
            status_code = 503

        return JsonResponse(data, status=status_code, json_dumps_params={"indent": 2})


class HeartbeatView(View):
    """
    This view handles the heartbeat check which determines if
    the application is healthy and running.

    It returns a JSON response containing the heartbeat information.
    """

    @disable_caching
    @log_request
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        db_conn = connections["default"]
        try:
            db_conn.cursor()
            healthy = True
        except OperationalError:
            healthy = False

        data = {
            "healthy": healthy,
            "services": {
                "lando": healthy,
            },
        }

        status = 200 if healthy else 502

        return JsonResponse(data, status=status, json_dumps_params={"indent": 2})


class LoadBalancerHeartbeatView(View):
    """
    This view handles the load balancer heartbeat check which determines if
    the application is healthy and running.

    It simply returns a JSON response with status 200.
    """

    @disable_caching
    @log_request
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return JsonResponse({}, status=200, json_dumps_params={"indent": 2})
