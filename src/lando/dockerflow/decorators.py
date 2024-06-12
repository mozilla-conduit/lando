import logging
import time
from functools import wraps

request_logger = logging.getLogger("__name__")


def log_request(view):
    @wraps(view)
    def _wrapped_view(self, request, *args, **kwargs):
        start_time = time.time()
        response = view(self, request, *args, **kwargs)
        end_time = time.time()

        summary = {
            "errno": 0 if response.status_code < 400 else 1,
            "agent": request.headers.get("User-Agent", ""),
            "lang": request.headers.get("Accept-Language", ""),
            "method": request.method,
            "path": request.path,
            "code": response.status_code,
            "t": int(1000 * (end_time - start_time)),
        }

        request_logger.info("Request Summary: ", extra=summary)

        return response

    return _wrapped_view


def disable_caching(view):
    @wraps(view)
    def _wrapped_view(self, request, *args, **kwargs):
        response = view(self, request, *args, **kwargs)

        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"

        return response

    return _wrapped_view
