# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import redis
import requests
import requests_mock
from django.core.cache import cache
from django.http import JsonResponse as JSONResponse
from django.test import Client

from django.conf import settings
from lando.api.legacy.mocks.auth import TEST_JWKS, MockAuth0
from lando.api.legacy.phabricator import PhabricatorClient
from lando.api.legacy.projects import (
    CHECKIN_PROJ_SLUG,
    RELMAN_PROJECT_SLUG,
    SEC_APPROVAL_PROJECT_SLUG,
    SEC_PROJ_SLUG,
)
from lando.api.legacy.repos import SCM_LEVEL_1, SCM_LEVEL_3, Repo
from lando.api.legacy.transplants import CODE_FREEZE_OFFSET, tokens_are_equal
from lando.api.tests.mocks import PhabricatorDouble, TreeStatusDouble

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
""".strip()

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
""".strip()

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
""".strip()


@pytest.fixture
def app():
    class _config:
        """Bridge legacy testing config with new config."""
        def __init__(self, overrides: dict = None):
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
        config = _config({
            "TESTING": True,
            "CACHE_DISABLED": True,
        })

    return _app()


@pytest.fixture
def normal_patch():
    """Return one of several "normal" patches."""
    _patches = [
        PATCH_NORMAL_1,
        PATCH_NORMAL_2,
        PATCH_NORMAL_3,
    ]

    def _patch(number=0):
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


# Are we running tests under local docker-compose or under CI?
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
    # Overwrite any externally set DATABASE_URL with a unittest-only database URL.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres:password@lando-api.db/lando_api_test"
    )
    monkeypatch.setenv("LANDO_UI_URL", "http://lando-ui.test")
    monkeypatch.setenv("PHABRICATOR_URL", "http://phabricator.test")
    monkeypatch.setenv("PHABRICATOR_ADMIN_API_KEY", "api-thiskeymustbe32characterslen")
    monkeypatch.setenv(
        "PHABRICATOR_UNPRIVILEGED_API_KEY", "api-thiskeymustbe32characterslen"
    )
    monkeypatch.setenv("BUGZILLA_URL", "http://bmo.test")
    monkeypatch.setenv("BUGZILLA_URL", "asdfasdfasdfasdfasdfasdf")
    monkeypatch.setenv("OIDC_IDENTIFIER", "lando-api")
    monkeypatch.setenv("OIDC_DOMAIN", "lando-api.auth0.test")
    # Explicitly shut off cache use for all tests.  Tests can re-enable the cache
    # with the redis_cache fixture.
    monkeypatch.delenv("CACHE_REDIS_HOST", raising=False)
    monkeypatch.delenv("CSP_REPORTING_URL", raising=False)
    # Don't suppress email in tests, but point at localhost so that any
    # real attempt would fail.
    monkeypatch.setenv("MAIL_SERVER", "localhost")
    monkeypatch.delenv("MAIL_SUPPRESS_SEND", raising=False)


@pytest.fixture
def request_mocker():
    """Yield a requests Mocker for response factories."""
    with requests_mock.mock() as m:
        yield m


@pytest.fixture
def phabdouble(monkeypatch):
    """Mock the Phabricator service and build fake response objects."""
    yield PhabricatorDouble(monkeypatch)


@pytest.fixture
def treestatusdouble(monkeypatch, treestatus_url):
    """Mock the Tree Status service and build fake responses."""
    yield TreeStatusDouble(monkeypatch, treestatus_url)


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
def jwks(monkeypatch):
    monkeypatch.setattr("lando.api.legacy.auth.get_jwks", lambda *args, **kwargs: TEST_JWKS)


@pytest.fixture
def auth0_mock(jwks, monkeypatch):
    mock_auth0 = MockAuth0()
    mock_userinfo_response = SimpleNamespace(
        status_code=200, json=lambda: mock_auth0.userinfo
    )
    monkeypatch.setattr(
        "lando.api.legacy.auth.fetch_auth0_userinfo", lambda token: mock_userinfo_response
    )
    return mock_auth0


@pytest.fixture
def mock_repo_config(monkeypatch):
    def set_repo_config(config):
        monkeypatch.setattr("lando.api.legacy.repos.REPO_CONFIG", config)

    return set_repo_config


@pytest.fixture
def mocked_repo_config(mock_repo_config):
    mock_repo_config(
        {
            "test": {
                "mozilla-central": Repo(
                    tree="mozilla-central",
                    url="http://hg.test",
                    access_group=SCM_LEVEL_3,
                    approval_required=False,
                ),
                "mozilla-uplift": Repo(
                    tree="mozilla-uplift",
                    url="http://hg.test/uplift",
                    access_group=SCM_LEVEL_3,
                    approval_required=True,
                ),
                "mozilla-new": Repo(
                    tree="mozilla-new",
                    url="http://hg.test/new",
                    access_group=SCM_LEVEL_3,
                    commit_flags=[("VALIDFLAG1", "testing"), ("VALIDFLAG2", "testing")],
                ),
                "try": Repo(
                    tree="try",
                    url="http://hg.test/try",
                    push_path="http://hg.test/try",
                    pull_path="http://hg.test",
                    access_group=SCM_LEVEL_1,
                    short_name="try",
                    is_phabricator_repo=False,
                    force_push=True,
                ),
            }
        }
    )


@pytest.fixture
def set_confirmation_token_comparison(monkeypatch):
    mem = {"set": False, "val": None}

    def set_value(val):
        mem["set"] = True
        mem["val"] = val

    monkeypatch.setattr(
        "lando.api.legacy.transplants.tokens_are_equal",
        lambda t1, t2: mem["val"] if mem["set"] else tokens_are_equal(t1, t2),
    )
    return set_value


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


@pytest.fixture
def treestatus_url():
    """A string holding the Tree Status base URL."""
    return "http://treestatus.test"


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
def hg_test_bundle(request):
    return Path(request.fspath.dirname).joinpath("data", "test-repo.bundle")


@pytest.fixture
def hg_server(hg_test_bundle, tmpdir):
    # TODO: Select open port.
    port = "8000"
    hg_url = "http://localhost:" + port

    repo_dir = tmpdir.mkdir("hg_server")
    subprocess.run(["hg", "clone", hg_test_bundle, repo_dir], check=True, cwd="/")

    serve = subprocess.Popen(
        [
            "hg",
            "serve",
            "--config",
            "web.push_ssl=False",
            "--config",
            "web.allow_push=*",
            "-p",
            port,
            "-R",
            repo_dir,
        ]
    )
    if serve.poll() is not None:
        raise Exception("Failed to start the mercurial server.")
    # Wait until the server is running.
    for _i in range(10):
        try:
            requests.get(hg_url)
        except Exception:
            time.sleep(1)
        break

    yield hg_url
    serve.kill()


@pytest.fixture
def hg_clone(hg_server, tmpdir):
    clone_dir = tmpdir.join("hg_clone")
    subprocess.run(["hg", "clone", hg_server, clone_dir.strpath], check=True)
    return clone_dir


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
