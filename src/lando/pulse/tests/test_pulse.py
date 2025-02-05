from unittest import mock

import kombu
import pytest

from lando.pulse.pulse import PulseNotifier

# We need to import dependencies of the fixtures we use, even if we don't use those
# directly.
from lando.pushlog.tests.conftest import make_commit, make_hash, make_push, make_repo

# We need some local usage of those imported fixtures to satisfy the linters.
# This is it.
__all__ = ["make_commit", "make_hash", "make_push", "make_repo"]


@pytest.mark.django_db
def test__PulseNotifier(make_repo, make_commit, make_push, monkeypatch):
    connection = kombu.Connection("amqp://")
    notifier = PulseNotifier(connection)

    publish = mock.MagicMock()
    monkeypatch.setattr(
        "kombu.Producer.publish",
        publish,
    )

    repo = make_repo(1)
    commit = make_commit(repo=repo, seqno=1)
    push = make_push(repo=repo, commits=[commit])

    notifier.notify_push(push)

    assert publish.call_args[1] == {"push_target": "", "force_push": True}
