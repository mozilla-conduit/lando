import pytest

from lando.api.legacy.treestatus import (
    TreeStatusCommunicationException,
    TreeStatusError,
)


@pytest.mark.django_db
def test_app_wide_headers_set(client):
    response = client.get("/__version__")
    assert response.status_code == 200
    assert "X-Frame-Options" in response.headers
    assert "X-Content-Type-Options" in response.headers
    assert "Content-Security-Policy" in response.headers

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


# See bug 1927163.
@pytest.mark.xfail(strict=True)
@pytest.mark.django_db
def test_app_wide_headers_set_for_api_endpoints(client):
    response = client.get("/__version__")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"


@pytest.mark.django_db
def test_app_wide_headers_csp_report_uri(app, client):
    app.config["CSP_REPORTING_URL"] = None
    response = client.get("/__version__")
    assert response.status_code == 200
    assert "report-uri" not in response.headers["Content-Security-Policy"]

    app.config["CSP_REPORTING_URL"] = "/__cspreport__"
    response = client.get("/__version__")
    assert response.status_code == 200
    assert "report-uri /__cspreport__" in (response.headers["Content-Security-Policy"])


@pytest.mark.skip
def test_treestatus_exception_handled(db, app, client):
    # We need to tell Flask to handle exceptions as if it were in a production
    # environment.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/__testing__/treestatus_exception1")
    def treestatus_exception1():
        raise TreeStatusCommunicationException("OOPS!")

    @app.route("/__testing__/treestatus_exception2")
    def treestatus_exception2():
        raise TreeStatusError(
            404,
            {
                "detail": "No such tree",
                "instance": "about:blank",
                "status": 404,
                "title": "404 Not Found: No such tree",
                "type": "about:blank",
            },
        )

    response = client.get("__testing__/treestatus_exception1")
    assert response.status_code == 500
    assert response.json["title"] == "Tree Status Error"

    response = client.get("__testing__/treestatus_exception2")
    assert response.status_code == 500
    assert response.json["title"] == "Tree Status Error"
