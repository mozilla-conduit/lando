from django.db import connection
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views import View

from lando.dockerflow.decorators import disable_caching, log_request


class DockerflowView(View):
    """
    This is the base class view for all Dockerflow related views.

    It handles common functionality needed by all Dockerflow views.
    """

    @disable_caching
    @log_request
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _json_response(data, status):
        return JsonResponse(data, status=status, json_dumps_params={"indent": 2})


class VersionView(DockerflowView):
    """
    This view handles the version information of Lando.

    It returns a JSON response containing the version information.
    """

    def get(self, request):
        status = 200
        try:
            from lando.version import version
        except ImportError:
            data = {"error": "Service Unavailable"}
            status = 503
        else:
            data = {
                "version": version,
            }

        return self._json_response(data=data, status=status)


class HeartbeatView(DockerflowView):
    """
    This view handles the heartbeat check which determines if
    the application is healthy and running.

    It returns a JSON response containing the heartbeat information.
    """

    def get(self, request):
        healthy = True
        try:
            connection.ensure_connection()
        except OperationalError:
            healthy = False

        data = {
            "healthy": healthy,
            "services": {
                "lando": healthy,
            },
        }

        status = 200 if healthy else 503

        return self._json_response(data=data, status=status)


class LoadBalancerHeartbeatView(DockerflowView):
    """
    This view handles the load balancer heartbeat check which determines if
    the application is healthy and running.

    It simply returns a JSON response with status 200.
    """

    def get(self, request):
        return self._json_response(data={}, status=200)
