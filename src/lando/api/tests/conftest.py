import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest import mock

import pytest
import redis
import requests_mock
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse
from django.http import JsonResponse as JSONResponse
from django.test import Client

import lando.api.legacy.api.stacks as legacy_api_stacks
import lando.api.legacy.api.transplants as legacy_api_transplants
from lando.api.legacy.api.landing_jobs import LandingJobApiView
from lando.api.legacy.projects import (
    CHECKIN_PROJ_SLUG,
    RELMAN_PROJECT_SLUG,
    SEC_APPROVAL_PROJECT_SLUG,
    SEC_PROJ_SLUG,
)
from lando.api.legacy.transplants import CODE_FREEZE_OFFSET
from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.api.legacy.workers.uplift_worker import (
    UpliftWorker,
)
from lando.api.tests.mocks import PhabricatorDouble
from lando.main.models import JobStatus, Repo, Revision
from lando.main.models.uplift import (
    MultiTrainUpliftRequest,
    RevisionUpliftJob,
    UpliftAssessment,
    UpliftJob,
)
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.support import LegacyAPIException
from lando.utils.phabricator import PhabricatorClient


@pytest.fixture
def app():
    class _config:
        """Bridge legacy testing config with new config."""

        def __init__(self, overrides: dict | None = None):
            self.overrides = overrides or {}

        def __getitem__(self, key):
            if key in self.overrides:
                return self.overrides[key]
            return getattr(settings, key)

        def __setitem__(self, key, value):
            setattr(settings, key, value)

    class _app:
        class test_request_context:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def __enter__(self):
                return Client(*self.args, **self.kwargs)

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        config = _config(
            {
                "TESTING": True,
                "CACHE_DISABLED": True,
            }
        )

    return _app()


class JSONClient(Client):
    """Custom Flask test client that sends JSON by default.

    HTTP methods have a 'json=...' keyword that will JSON-encode the
    given data.

    All requests' content-type is automatically set to 'application/json'
    unless overridden.
    """

    def open(self, *args, **kwargs):
        """Send a HTTP request.

        Args:
            json: An object to be JSON-encoded. Cannot be used at the same time
                as the 'data' keyword arg.
            content_type: optional, will override the default
                of 'application/json'.
        """
        assert not (("data" in kwargs) and ("json" in kwargs))
        kwargs.setdefault("content_type", "application/json")
        if "json" in kwargs:
            kwargs["data"] = json.dumps(kwargs["json"], sort_keys=True)
            del kwargs["json"]
        return super(JSONClient, self).open(*args, **kwargs)


# Are we running tests under local docker compose or under CI?
# Assume that if we are running in an environment with the external services we
# need then the appropriate variables will be present in the environment.
#
# Set this as a module-level variable so that we can query os.environ without any
# monkeypatch modifications.
EXTERNAL_SERVICES_SHOULD_BE_PRESENT = (
    "DATABASE_URL" in os.environ or os.getenv("CI") or "CACHE_REDIS_HOST" in os.environ
)


@pytest.fixture
def docker_env_vars(versionfile, monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("VERSION_PATH", str(versionfile))
    monkeypatch.setenv("PHABRICATOR_URL", "http://phabricator.test")
    monkeypatch.setenv("PHABRICATOR_ADMIN_API_KEY", "api-thiskeymustbe32characterslen")
    monkeypatch.setenv(
        "PHABRICATOR_UNPRIVILEGED_API_KEY", "api-thiskeymustbe32characterslen"
    )
    monkeypatch.setenv("BUGZILLA_URL", "http://bmo.test")
    monkeypatch.setenv("BUGZILLA_URL", "asdfasdfasdfasdfasdfasdf")
    monkeypatch.setenv("OIDC_IDENTIFIER", "lando-api")
    monkeypatch.setenv("OIDC_DOMAIN", "lando-api.auth0.test")
    monkeypatch.delenv("CSP_REPORTING_URL", raising=False)


@pytest.fixture
def request_mocker():
    """Yield a requests Mocker for response factories."""
    with requests_mock.mock() as m:
        yield m


@pytest.fixture
def phabdouble(monkeypatch):
    """Mock the Phabricator service and build fake response objects."""
    phabdouble = PhabricatorDouble(monkeypatch)

    # Create required projects.
    phabdouble.project(SEC_PROJ_SLUG)
    phabdouble.project(CHECKIN_PROJ_SLUG)
    phabdouble.project(SEC_APPROVAL_PROJECT_SLUG)
    phabdouble.project(
        RELMAN_PROJECT_SLUG,
        attachments={"members": {"members": [{"phid": "PHID-USER-1"}]}},
    )
    yield phabdouble


@pytest.fixture
def mock_uplift_email_tasks(monkeypatch):
    success_task = mock.MagicMock()
    failure_task = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.uplift_worker.send_uplift_success_email",
        success_task,
    )
    monkeypatch.setattr(
        "lando.api.legacy.workers.uplift_worker.send_uplift_failure_email",
        failure_task,
    )
    return success_task, failure_task


@pytest.fixture
def secure_project(phabdouble):
    return phabdouble.project(SEC_PROJ_SLUG)


@pytest.fixture
def checkin_project(phabdouble):
    return phabdouble.project(CHECKIN_PROJ_SLUG)


@pytest.fixture
def sec_approval_project(phabdouble):
    return phabdouble.project(SEC_APPROVAL_PROJECT_SLUG)


@pytest.fixture
def release_management_project(phabdouble):
    return phabdouble.project(
        RELMAN_PROJECT_SLUG,
        attachments={"members": {"members": [{"phid": "PHID-USER-1"}]}},
    )


@pytest.fixture
def versionfile(tmpdir):
    """Provide a temporary version.json on disk."""
    v = tmpdir.mkdir("app").join("version.json")
    v.write(
        json.dumps(
            {
                "source": "https://github.com/mozilla-conduit/lando-api",
                "version": "0.0.0",
                "commit": "",
                "build": "test",
            }
        )
    )
    return v


@pytest.fixture
def mock_repo_config(monkeypatch):
    def set_repo_config(config):
        monkeypatch.setattr("lando.api.legacy.repos.REPO_CONFIG", config)

    return set_repo_config


@pytest.fixture
def hg_landing_worker(landing_worker_instance):
    worker = landing_worker_instance(
        name="test-hg-worker",
        scm=SCM_TYPE_HG,
    )
    return LandingWorker(worker)


@pytest.fixture
def git_landing_worker(landing_worker_instance):
    worker = landing_worker_instance(
        name="test-git-worker",
        scm=SCM_TYPE_GIT,
    )
    return LandingWorker(worker)


@pytest.fixture
def get_landing_worker(hg_landing_worker, git_landing_worker):
    workers = {
        SCM_TYPE_GIT: git_landing_worker,
        SCM_TYPE_HG: hg_landing_worker,
    }

    def _get_landing_worker(scm_type):
        return workers[scm_type]

    return _get_landing_worker


@pytest.fixture
def uplift_worker(landing_worker_instance, treestatusdouble):
    worker = landing_worker_instance(
        name="uplift-worker-git",
        scm=SCM_TYPE_GIT,
    )
    return UpliftWorker(worker)


@pytest.fixture
def get_phab_client(app):
    def get_client(api_key=None):
        api_key = api_key or settings.PHABRICATOR_UNPRIVILEGED_API_KEY
        return PhabricatorClient(settings.PHABRICATOR_URL, api_key)

    return get_client


@pytest.fixture
def redis_cache(app):
    cache.init_app(
        app, config={"CACHE_TYPE": "redis", "CACHE_REDIS_HOST": "redis.cache"}
    )
    try:
        cache.clear()
    except redis.exceptions.ConnectionError:
        if EXTERNAL_SERVICES_SHOULD_BE_PRESENT:
            raise
        else:
            pytest.skip("Could not connect to Redis")
    yield cache
    cache.clear()
    cache.init_app(app, config={"CACHE_TYPE": "null", "CACHE_NO_NULL_WARNING": True})


def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, JSONResponse) and isinstance(right, int) and op == "==":
        # Hook failures when comparing JSONResponse objects so we get the detailed
        # failure description from inside the response object contents.
        #
        # The following example code would trigger this hook:
        #
        #   response = client.get()
        #   assert response == 200  # Fails if response is HTTP 401, triggers this hook
        return [
            f"Mismatch in status code for response: {left.status_code} != {right}",
            "",
            f"    Response JSON: {left.json}",
        ]


@pytest.fixture
def patch_directory(request):
    return Path(request.fspath.dirname).joinpath("patches")


@pytest.fixture
def register_codefreeze_uri(request_mocker):
    request_mocker.register_uri(
        "GET",
        "https://product-details.mozilla.org/1.0/firefox_versions.json",
        json={
            "NEXT_SOFTFREEZE_DATE": "2122-01-01",
            "NEXT_MERGE_DATE": "2122-01-01",
        },
    )


@pytest.fixture
def codefreeze_datetime(request_mocker):
    utc_offset = CODE_FREEZE_OFFSET
    dates = {
        "today": datetime(2000, 1, 5, 0, 0, 0, tzinfo=timezone.utc),
        f"two_days_ago {utc_offset}": datetime(2000, 1, 3, 0, 0, 0),
        f"tomorrow {utc_offset}": datetime(2000, 1, 6, 0, 0, 0),
        f"four_weeks_from_today {utc_offset}": datetime(2000, 2, 3, 0, 0, 0),
        f"five_weeks_from_today {utc_offset}": datetime(2000, 2, 10, 0, 0, 0),
    }

    class Mockdatetime:
        @classmethod
        def now(cls, tz):
            return dates["today"]

        @classmethod
        def strptime(cls, date_string, fmt):
            return dates[f"{date_string}"]

    return Mockdatetime


@pytest.fixture
def fake_request():
    class FakeUser:
        def has_perm(self, permission, *args, **kwargs):
            return permission in self.permissions

        def __init__(self, is_authenticated=True, has_email=True, permissions=None):
            self.is_authenticated = is_authenticated
            self.permissions = permissions or ()
            if has_email:
                self.email = "email@example.org"
            else:
                self.email = ""

    class FakeRequest:
        def __init__(self, *args, **kwargs):
            self.body = "{}"
            if "body" in kwargs:
                self.body = kwargs.pop("body")
            self.method = kwargs.pop("method", "GET")
            self.user = FakeUser(*args, **kwargs)

    return FakeRequest


@pytest.fixture
def mock_permissions():
    return (
        "main.scm_level_1",
        "main.scm_level_2",
        "main.scm_level_3",
        "main.scm_conduit",
    )


@pytest.fixture
def proxy_client(monkeypatch, fake_request):
    """A client that bridges tests designed to work with the API.

    Most tests that use the API no longer need to access those endpoints through
    the API as the data can be fetched directly within the application. This client
    is a temporary implementation to bridge tests and minimize the number of changes
    needed to the tests during the porting process.

    This client should be removed and all the tests that depend on it should be
    reimplemented to not need a response or response-like object.
    """

    class MockResponse:
        """Mock response class to satisfy some requirements of tests."""

        # NOTE: The methods tested that rely on this class should be reimplemented
        # to no longer need the structure of a response to function.
        def __init__(self, status_code=200, json=None):
            self.json = json or {}
            self.status_code = status_code
            self.content_type = (
                "application/json" if status_code < 400 else "application/problem+json"
            )

    class ProxyClient:
        request = fake_request()

        def _handle__get__stacks__id(self, path):
            revision_id = int(path.removeprefix("/stacks/D"))
            json_response = legacy_api_stacks.get(self.request, revision_id)
            if isinstance(json_response, HttpResponse):
                # In some cases, an actual response object is returned.
                return json_response
            # In other cases, just the data is returned, and it should be
            # mapped to a response.

            # Remove the `stack` field as it isn't JSON serializable
            # and isn't required in the proxy client tests.
            json_response.pop("stack")

            return MockResponse(json=json.loads(json.dumps(json_response)))

        def _handle__get__transplants__id(self, path):
            stack_revision_id = path.removeprefix("/transplants?stack_revision_id=")
            result = legacy_api_transplants.get_list(
                self.request, stack_revision_id=stack_revision_id
            )
            if isinstance(result, tuple):
                # For these endpoints, some responses contain different status codes
                # which are represented as the second item in a tuple.
                json_response, status_code = result
                return MockResponse(
                    json=json.loads(json.dumps(json_response)),
                    status_code=status_code,
                )
            # In the rest of the cases, the returned result is a response object.
            return result

        def _handle__post__transplants__dryrun(self, **kwargs):
            json_response = legacy_api_transplants.dryrun(self.request, kwargs["json"])
            return MockResponse(json=json.loads(json.dumps(json_response)))

        def _handle__post__transplants(self, path, **kwargs):
            try:
                json_response, status_code = legacy_api_transplants.post(
                    self.request, kwargs["json"]
                )
            except LegacyAPIException as e:
                # Handle exceptions and pass along the status code to the response object.
                if e.extra:
                    return MockResponse(json=e.extra, status_code=e.status)
                if e.json_detail:
                    return MockResponse(json=e.json_detail, status_code=e.status)
                return MockResponse(json=e.args, status_code=e.status)
            except Exception as e:
                # TODO: double check that this is a thing in legacy?
                # Added this due to a validation error (test_transplant_wrong_landing_path_format)
                return MockResponse(json=[f"error ({e})"], status_code=400)
            return MockResponse(
                json=json.loads(json.dumps(json_response)), status_code=status_code
            )

        def _handle__put__landing_jobs__id(self, path, **kwargs):
            job_id = int(path.removeprefix("/landing_jobs/"))
            landing_job_api = LandingJobApiView()
            response = landing_job_api.put(self.request, job_id)
            return MockResponse(json=json.loads(response.content))

        def get(self, path, *args, **kwargs):
            """Handle various get endpoints."""
            if path.startswith("/stacks/D"):
                return self._handle__get__stacks__id(path)

            if path.startswith("/transplants?"):
                return self._handle__get__transplants__id(path)

        def post(self, path, **kwargs):
            """Handle various post endpoints."""
            if "permissions" in kwargs:
                self.request = fake_request(permissions=kwargs["permissions"])

            if path.startswith("/transplants/dryrun"):
                return self._handle__post__transplants__dryrun(**kwargs)

            if path == "/transplants":
                return self._handle__post__transplants(path, **kwargs)

        def put(self, path, **kwargs):
            """Handle put endpoint."""
            request_dict = {}

            if "permissions" in kwargs:
                request_dict["permissions"] = kwargs["permissions"]

            if "json" in kwargs:
                request_dict["body"] = json.dumps(kwargs["json"])

            self.request = fake_request(method="PUT", **request_dict)

            if path.startswith("/landing_jobs/"):
                return self._handle__put__landing_jobs__id(path, **kwargs)

    return ProxyClient()


@pytest.fixture
def authenticated_client(user, user_plaintext_password, client):
    client.login(username=user.username, password=user_plaintext_password)
    return client


@pytest.fixture
def make_uplift_job_with_revisions() -> (
    Callable[[Repo, User, list[Revision]], UpliftJob]
):
    """Create assessment, multi-request, revisions, and a single UpliftJob associated to them."""

    def _make_uplift_job_with_revisions(
        repo: Repo, user: User, revisions: list[Revision]
    ) -> UpliftJob:
        # 1) Assessment
        assessment = UpliftAssessment.objects.create(
            user=user,
            user_impact="Medium",
            covered_by_testing="yes",
            fix_verified_in_nightly="yes",
            needs_manual_qe_testing="no",
            qe_testing_reproduction_steps="",
            risk_associated_with_patch="low",
            risk_level_explanation="low risk",
            string_changes="none",
            is_android_affected="no",
        )

        # 2) Multi-request holding the ordered D-IDs
        multi = MultiTrainUpliftRequest.objects.create(
            user=user,
            assessment=assessment,
            requested_revision_ids=[revision.revision_id for revision in revisions],
        )

        # 3) One job for the target repo
        job = UpliftJob.objects.create(
            status=JobStatus.SUBMITTED,
            requester_email=user.email,
            target_repo=repo,
            multi_request=multi,
            attempts=1,
        )

        # 4) Attach and order revisions via through table
        for idx, revision in enumerate(revisions):
            RevisionUpliftJob.objects.create(
                uplift_job=job, revision=revision, index=idx
            )

        return job

    return _make_uplift_job_with_revisions
