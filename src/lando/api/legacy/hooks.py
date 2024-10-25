import logging
import time
from typing import Optional

from flask import (
    Flask,
    Response,
    current_app,
    g,
    request,
)

from lando.api.legacy.sentry import sentry_sdk
from lando.api.legacy.treestatus import TreeStatusException
from lando.main.models.configuration import ConfigurationKey, ConfigurationVariable
from lando.main.support import FlaskApi, problem
from lando.utils.phabricator import PhabricatorAPIException

logger = logging.getLogger(__name__)
request_logger = logging.getLogger("request.summary")


def check_maintenance() -> Optional[Response]:
    """Returns a 503 error if the API maintenance flag is on."""
    excepted_endpoints = (
        "dockerflow.heartbeat",
        "dockerflow.version",
        "dockerflow.lbheartbeat",
    )
    if request.endpoint in excepted_endpoints:
        return

    in_maintenance = ConfigurationVariable.get(
        ConfigurationKey.API_IN_MAINTENANCE, False
    )
    if in_maintenance:
        return FlaskApi.get_response(
            problem(
                503,
                "API IN MAINTENANCE",
                f"The API is in maintenance, please try again later. {request.endpoint}",
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/503",
            )
        )


def request_logging_before_request():
    g._request_start_timestamp = time.time()


def request_logging_after_request(response: Response) -> Response:
    summary = {
        "errno": 0 if response.status_code < 400 else 1,
        "agent": request.headers.get("User-Agent", ""),
        "lang": request.headers.get("Accept-Language", ""),
        "method": request.method,
        "path": request.path,
        "code": response.status_code,
    }

    start = g.get("_request_start_timestamp", None)
    if start is not None:
        summary["t"] = int(1000 * (time.time() - start))

    request_logger.info("request summary", extra=summary)

    return response


def handle_phabricator_api_exception(exc: PhabricatorAPIException) -> Response:
    sentry_sdk.capture_exception()
    logger.error(
        "phabricator exception",
        extra={"error_code": exc.error_code, "error_info": exc.error_info},
        exc_info=exc,
    )

    if current_app.propagate_exceptions:
        # Mimic the behaviour of Flask.handle_exception() and re-raise the full
        # traceback in test and debug environments.
        raise exc

    return FlaskApi.get_response(
        problem(
            500,
            "Phabricator Error",
            "An unexpected error was received from Phabricator",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    )


def handle_treestatus_exception(exc: TreeStatusException) -> Response:
    sentry_sdk.capture_exception()
    logger.error("Tree Status exception", exc_info=exc)

    if current_app.propagate_exceptions:
        # Mimic the behaviour of Flask.handle_exception() and re-raise the full
        # traceback in test and debug environments.
        raise exc

    return FlaskApi.get_response(
        problem(
            500,
            "Tree Status Error",
            "An unexpected error was received from Tree Status",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    )


def initialize_hooks(flask_app: Flask):
    flask_app.before_request(check_maintenance)
    flask_app.before_request(request_logging_before_request)
    flask_app.after_request(request_logging_after_request)

    flask_app.register_error_handler(
        PhabricatorAPIException, handle_phabricator_api_exception
    )
    flask_app.register_error_handler(TreeStatusException, handle_treestatus_exception)
