# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import Mock

import redis

from lando.api.legacy.auth import auth0_subsystem
from lando.api.legacy.cache import cache_subsystem
from lando.api.legacy.phabricator import PhabricatorAPIException, phabricator_subsystem


def test_phabricator_healthy(app, phabdouble):
    assert phabricator_subsystem.healthy() is True


def test_phabricator_unhealthy(app, monkeypatch):
    def raises(*args, **kwargs):
        raise PhabricatorAPIException

    monkeypatch.setattr("landoapi.phabricator.PhabricatorClient.call_conduit", raises)
    assert phabricator_subsystem.healthy() is not True


def test_cache_healthy(redis_cache):
    assert cache_subsystem.healthy() is True


def test_cache_unhealthy_configuration():
    assert cache_subsystem.healthy() is not True


def test_cache_unhealthy_service(redis_cache, monkeypatch):
    mock_cache = Mock(redis_cache)
    mock_cache.cache._read_client.ping.side_effect = redis.TimeoutError
    monkeypatch.setattr("landoapi.cache.cache", mock_cache)
    monkeypatch.setattr("landoapi.cache.RedisCache", type(mock_cache.cache))

    health = cache_subsystem.healthy()
    assert health is not True
    assert health.startswith("RedisError:")


def test_auth0_healthy(app, jwks):
    assert auth0_subsystem.healthy() is True


def test_auth0_unhealthy(app):
    assert auth0_subsystem.healthy() is not True
