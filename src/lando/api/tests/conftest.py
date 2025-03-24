import json
import os
import pathlib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import py
import pytest
import redis
import requests_mock
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.http import JsonResponse as JSONResponse
from django.test import Client

import lando.api.legacy.api.landing_jobs as legacy_api_landing_jobs
import lando.api.legacy.api.stacks as legacy_api_stacks
import lando.api.legacy.api.transplants as legacy_api_transplants
from lando.api.legacy.projects import (
    CHECKIN_PROJ_SLUG,
    RELMAN_PROJECT_SLUG,
    SEC_APPROVAL_PROJECT_SLUG,
    SEC_PROJ_SLUG,
)
from lando.api.legacy.transplants import CODE_FREEZE_OFFSET
from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.api.tests.mocks import PhabricatorDouble, TreeStatusDouble
from lando.main.models import SCM_LEVEL_1, SCM_LEVEL_3, Repo, Worker
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG
from lando.main.support import LegacyAPIException
from lando.main.tests.conftest import git_repo, git_repo_seed
from lando.utils.phabricator import PhabricatorClient

# We need some local usage of those imported fixtures to satisfy the linters.
# This is it.
__all__ = ["git_repo", "git_repo_seed"]

PATCH_NORMAL_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()

PATCH_NORMAL_2 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,2 +1,3 @@
 TEST
 adding another line
+adding one more line
""".lstrip()

PATCH_NORMAL_3 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
deleted file mode 100644
--- a/test.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-TEST
diff --git a/blah.txt b/blah.txt
new file mode 100644
--- /dev/null
+++ b/blah.txt
@@ -0,0 +1,1 @@
+TEST
""".lstrip()


@pytest.fixture
def app():
    class _config:
        """Bridge legacy testing config with new config."""

        def __init__(self, overrides: dict | None = None):
            self.overrides = overrides or {}

        def __getitem__(self, key):  # noqa: ANN001, ANN204
            if key in self.overrides:
                return self.overrides[key]
            return getattr(settings, key)

        def __setitem__(self, key, value):  # noqa: ANN001
            setattr(settings, key, value)

    class _app:
        class test_request_context:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def __enter__(self):  # noqa: ANN204
                return Client(*self.args, **self.kwargs)

            def __exit__(self, exc_type, exc_val, exc_tb):  # noqa: ANN001
                pass

        config = _config(
            {
                "TESTING": True,
                "CACHE_DISABLED": True,
            }
        )

    return _app()


@pytest.fixture
def normal_patch():
    """Return one of several "normal" patches."""
    _patches = [
        PATCH_NORMAL_1,
        PATCH_NORMAL_2,
        PATCH_NORMAL_3,
    ]

    def _patch(number=0):  # noqa: ANN001
        return _patches[number]

    return _patch


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
def docker_env_vars(versionfile, monkeypatch):  # noqa: ANN001
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
def phabdouble(monkeypatch):  # noqa: ANN001
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
def treestatusdouble(monkeypatch, treestatus_url):  # noqa: ANN001
    """Mock the Tree Status service and build fake responses."""
    yield TreeStatusDouble(monkeypatch, treestatus_url)


@pytest.fixture
def secure_project(phabdouble):  # noqa: ANN001
    return phabdouble.project(SEC_PROJ_SLUG)


@pytest.fixture
def checkin_project(phabdouble):  # noqa: ANN001
    return phabdouble.project(CHECKIN_PROJ_SLUG)


@pytest.fixture
def sec_approval_project(phabdouble):  # noqa: ANN001
    return phabdouble.project(SEC_APPROVAL_PROJECT_SLUG)


@pytest.fixture
def release_management_project(phabdouble):  # noqa: ANN001
    return phabdouble.project(
        RELMAN_PROJECT_SLUG,
        attachments={"members": {"members": [{"phid": "PHID-USER-1"}]}},
    )


@pytest.fixture
def versionfile(tmpdir):  # noqa: ANN001
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
def mock_repo_config(monkeypatch):  # noqa: ANN001
    def set_repo_config(config):  # noqa: ANN001
        monkeypatch.setattr("lando.api.legacy.repos.REPO_CONFIG", config)

    return set_repo_config


@pytest.fixture
def mocked_repo_config(mock_repo_config):  # noqa: ANN001
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central",
        url="http://hg.test",
        required_permission=SCM_LEVEL_3,
        approval_required=False,
    )
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-uplift",
        url="http://hg.test/uplift",
        required_permission=SCM_LEVEL_3,
        approval_required=True,
    )
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-new",
        url="http://hg.test/new",
        required_permission=SCM_LEVEL_3,
        commit_flags=[("VALIDFLAG1", "testing"), ("VALIDFLAG2", "testing")],
    )
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="try",
        url="http://hg.test/try",
        push_path="http://hg.test/try",
        pull_path="http://hg.test",
        required_permission=SCM_LEVEL_1,
        short_name="try",
        is_phabricator_repo=False,
        force_push=True,
    )
    # Copied from legacy "local-dev". Should have been in mocked repos.
    Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="uplift-target",
        url="http://hg.test",  # TODO: fix this? URL is probably incorrect.
        required_permission=SCM_LEVEL_1,
        approval_required=True,
        milestone_tracking_flag_template="cf_status_firefox{milestone}",
    )


@pytest.fixture
def landing_worker_instance(mocked_repo_config):  # noqa: ANN001
    def _instance(scm, **kwargs):  # noqa: ANN001
        worker = Worker.objects.create(sleep_seconds=0.1, scm=scm, **kwargs)
        worker.applicable_repos.set(Repo.objects.filter(scm_type=scm))
        return worker

    return _instance


@pytest.fixture
def hg_landing_worker(landing_worker_instance):  # noqa: ANN001
    worker = landing_worker_instance(
        name="test-hg-worker",
        scm=SCM_TYPE_HG,
    )
    return LandingWorker(worker)


@pytest.fixture
def git_landing_worker(landing_worker_instance):  # noqa: ANN001
    worker = landing_worker_instance(
        name="test-git-worker",
        scm=SCM_TYPE_GIT,
    )
    return LandingWorker(worker)


@pytest.fixture
def get_landing_worker(hg_landing_worker, git_landing_worker):  # noqa: ANN001
    workers = {
        SCM_TYPE_GIT: git_landing_worker,
        SCM_TYPE_HG: hg_landing_worker,
    }

    def _get_landing_worker(scm_type):  # noqa: ANN001
        return workers[scm_type]

    return _get_landing_worker


@pytest.fixture
def get_phab_client(app):  # noqa: ANN001
    def get_client(api_key=None):  # noqa: ANN001
        api_key = api_key or settings.PHABRICATOR_UNPRIVILEGED_API_KEY
        return PhabricatorClient(settings.PHABRICATOR_URL, api_key)

    return get_client


@pytest.fixture
def redis_cache(app):  # noqa: ANN001
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


@pytest.fixture
def treestatus_url():
    """A string holding the Tree Status base URL."""
    return "http://treestatus.test"


def pytest_assertrepr_compare(op, left, right):  # noqa: ANN001
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
def patch_directory(request):  # noqa: ANN001
    return Path(request.fspath.dirname).joinpath("patches")


@pytest.fixture
def register_codefreeze_uri(request_mocker):  # noqa: ANN001
    request_mocker.register_uri(
        "GET",
        "https://product-details.mozilla.org/1.0/firefox_versions.json",
        json={
            "NEXT_SOFTFREEZE_DATE": "2122-01-01",
            "NEXT_MERGE_DATE": "2122-01-01",
        },
    )


@pytest.fixture
def codefreeze_datetime(request_mocker):  # noqa: ANN001
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
        def now(cls, tz):  # noqa: ANN001, ANN206
            return dates["today"]

        @classmethod
        def strptime(cls, date_string, fmt):  # noqa: ANN001, ANN206
            return dates[f"{date_string}"]

    return Mockdatetime


@pytest.fixture
def fake_request():
    class FakeUser:
        def has_perm(self, permission, *args, **kwargs):  # noqa: ANN001
            return permission in self.permissions

        def __init__(
            self,
            is_authenticated=True,  # noqa: ANN001
            has_email=True,  # noqa: ANN001
            permissions=None,  # noqa: ANN001
        ):

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
def proxy_client(monkeypatch, fake_request):  # noqa: ANN001
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
        def __init__(self, status_code=200, json=None):  # noqa: ANN001
            self.json = json or {}
            self.status_code = status_code
            self.content_type = (
                "application/json" if status_code < 400 else "application/problem+json"
            )

    class ProxyClient:
        request = fake_request()

        def _handle__get__stacks__id(self, path):  # noqa: ANN001
            revision_id = int(path.removeprefix("/stacks/D"))
            json_response = legacy_api_stacks.get(self.request, revision_id)
            if isinstance(json_response, HttpResponse):
                # In some cases, an actual response object is returned.
                return json_response
            # In other cases, just the data is returned, and it should be
            # mapped to a response.
            return MockResponse(json=json.loads(json.dumps(json_response)))

        def _handle__get__transplants__id(self, path):  # noqa: ANN001
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

        def _handle__post__transplants(self, path, **kwargs):  # noqa: ANN001
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

        def _handle__put__landing_jobs__id(self, path, **kwargs):  # noqa: ANN001
            job_id = int(path.removeprefix("/landing_jobs/"))
            response = legacy_api_landing_jobs.put(self.request, job_id)
            return MockResponse(json=json.loads(response.content))

        def get(self, path, *args, **kwargs):  # noqa: ANN001
            """Handle various get endpoints."""
            if path.startswith("/stacks/D"):
                return self._handle__get__stacks__id(path)

            if path.startswith("/transplants?"):
                return self._handle__get__transplants__id(path)

        def post(self, path, **kwargs):  # noqa: ANN001
            """Handle various post endpoints."""
            if "permissions" in kwargs:
                self.request = fake_request(permissions=kwargs["permissions"])

            if path.startswith("/transplants/dryrun"):
                return self._handle__post__transplants__dryrun(**kwargs)

            if path == "/transplants":
                return self._handle__post__transplants(path, **kwargs)

        def put(self, path, **kwargs):  # noqa: ANN001
            """Handle put endpoint."""
            request_dict = {}
            if "permissions" in kwargs:
                request_dict["permissions"] = kwargs["permissions"]

            if "json" in kwargs:
                request_dict["body"] = json.dumps(kwargs["json"])

            self.request = fake_request(**request_dict)

            if path.startswith("/landing_jobs/"):
                return self._handle__put__landing_jobs__id(path, **kwargs)

    return ProxyClient()


@pytest.fixture
def authenticated_client(user, user_plaintext_password, client):  # noqa: ANN001
    client.login(username=user.username, password=user_plaintext_password)
    return client


@pytest.mark.django_db
def hg_repo_mc(
    hg_server: str,
    hg_clone: py.path,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    force_push: bool = False,
    push_target: str = "",
) -> Repo:
    params = {
        "required_permission": SCM_LEVEL_3,
        "url": hg_server,
        "push_path": hg_server,
        "pull_path": hg_server,
        "system_path": hg_clone.strpath,
        # The option below can be overriden in the parameters
        "approval_required": approval_required,
        "autoformat_enabled": autoformat_enabled,
        "force_push": force_push,
        "push_target": push_target,
    }
    repo = Repo.objects.create(
        scm_type=SCM_TYPE_HG,
        name="mozilla-central-hg",
        **params,
    )
    repo.save()
    return repo


@pytest.mark.django_db
def git_repo_mc(
    git_repo: pathlib.Path,
    tmp_path: pathlib.Path,
    *,
    approval_required: bool = False,
    autoformat_enabled: bool = False,
    force_push: bool = False,
    push_target: str = "",
) -> Repo:
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    params = {
        "required_permission": SCM_LEVEL_3,
        "url": str(git_repo),
        "push_path": str(git_repo),
        "pull_path": str(git_repo),
        "system_path": repos_dir / "git_repo",
        # The option below can be overriden in the parameters
        "approval_required": approval_required,
        "autoformat_enabled": autoformat_enabled,
        "force_push": force_push,
        "push_target": push_target,
    }

    repo = Repo.objects.create(
        scm_type=SCM_TYPE_GIT,
        name="mozilla-central-git",
        **params,
    )
    repo.save()
    repo.scm.prepare_repo(repo.pull_path)
    return repo


@pytest.fixture()
def repo_mc(
    # Git
    git_repo: pathlib.Path,
    tmp_path: pathlib.Path,
    # Hg
    hg_server: str,
    hg_clone: py.path,
) -> Callable:
    def factory(
        scm_type: str,
        *,
        approval_required: bool = False,
        autoformat_enabled: bool = False,
        force_push: bool = False,
        push_target: str = "",
    ) -> Repo:
        params = {
            "approval_required": approval_required,
            "autoformat_enabled": autoformat_enabled,
            "force_push": force_push,
            "push_target": push_target,
        }

        if scm_type == SCM_TYPE_GIT:
            return git_repo_mc(git_repo, tmp_path, **params)
        elif scm_type == SCM_TYPE_HG:
            return hg_repo_mc(hg_server, hg_clone, **params)
        raise Exception(f"Unknown SCM Type {scm_type=}")

    return factory
