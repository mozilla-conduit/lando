import kombu
from pytest import mock

from lando.pulse.pulse import PulseNotifier


def test__PulseNotifier(make_push, monkeypatch):
    connection = kombu.Connection("amqp://")
    notifier = PulseNotifier(connection)

    publish = mock.MagicMock()
    monkeypatch.setattr(
        "kombu.Producer.publish",
        publish,
    )

    push = make_push()

    notifier.notify_push(push)

    assert publish.call_args[1] == {"push_target": "", "force_push": True}
