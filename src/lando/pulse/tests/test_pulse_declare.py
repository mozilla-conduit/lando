import unittest.mock as mock
from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_pulse_declare(monkeypatch):
    mock_producer = mock.MagicMock()
    monkeypatch.setattr(
        "lando.pulse.pulse.PulseNotifier._make_producer", lambda cls: mock_producer
    )

    out = StringIO()
    call_command("pulse_declare", stdout=out)

    assert mock_producer.exchange.declare.call_count == 1
    assert "Declared exchange" in out.getvalue()
