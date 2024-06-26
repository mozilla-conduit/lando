from __future__ import annotations

import logging

from django.conf import settings
from flask_caching import Cache
from flask_caching.backends.rediscache import RedisCache
from redis import RedisError

from lando.api.legacy.redis import SuppressRedisFailure
from lando.api.legacy.systems import Subsystem

# 60s * 60m * 24h
DEFAULT_CACHE_KEY_TIMEOUT_SECONDS = 60 * 60 * 24

logger = logging.getLogger(__name__)
cache = Cache()
cache.suppress_failure = SuppressRedisFailure


class CacheSubsystem(Subsystem):
    name = "cache"

    def init_app(self, app):
        super().init_app(app)
        host = settings.CACHE_REDIS_HOST
        if settings.CACHE_DISABLED:
            # Default to not caching for testing.
            logger.warning("Cache initialized in null mode.")
            cache_config = {"CACHE_TYPE": "NullCache"}
        elif not host:
            logger.warning("Cache initialized in filesystem mode.")
            cache_config = {"CACHE_TYPE": "FileSystemCache", "CACHE_DIR": "/tmp/cache"}
        else:
            cache_config = {"CACHE_TYPE": "redis", "CACHE_REDIS_HOST": host}
            config_keys = ("CACHE_REDIS_PORT", "CACHE_REDIS_PASSWORD", "CACHE_REDIS_DB")
            for k in config_keys:
                v = self.flask_app.config.get(k)
                if v is not None:
                    cache_config[k] = v

        cache.init_app(self.flask_app, config=cache_config)

    def healthy(self) -> bool | str:
        if not isinstance(cache.cache, RedisCache):
            return "Cache is not configured to use redis"

        # Dirty, but if this breaks in the future we can instead
        # create our own redis-py client with its own connection
        # pool.
        redis = cache.cache._read_client

        try:
            redis.ping()
        except RedisError as exc:
            return "RedisError: {!s}".format(exc)

        return True


cache_subsystem = CacheSubsystem()
