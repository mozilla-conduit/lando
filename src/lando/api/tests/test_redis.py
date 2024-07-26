import logging

import pytest
from redis import RedisError

from lando.api.legacy.redis import SuppressRedisFailure


def test_suppress_redis_failure_logs_exceptions(caplog):
    caplog.set_level(logging.INFO)

    flag = False
    with SuppressRedisFailure():
        raise RedisError("Failure to be suppressed.")
        flag = True

    assert len(caplog.records) == 1
    assert not flag


def test_suppress_redis_failure_does_not_log_on_success(caplog):
    does_not_raise = False
    with SuppressRedisFailure():
        does_not_raise = True

    assert not caplog.records
    assert does_not_raise


def test_suppress_redis_failure_does_not_supress_other_exceptions(caplog):
    with pytest.raises(ValueError):
        with SuppressRedisFailure():
            raise ValueError("This should not be suppressed.")

    assert not caplog.records
