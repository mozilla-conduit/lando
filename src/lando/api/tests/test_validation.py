import pytest

from lando.api.legacy.validation import revision_id_to_int
from lando.main.support import LegacyAPIException


def test_convertion_success():
    assert revision_id_to_int("D123") == 123


@pytest.mark.parametrize("id", ["123D", "123", "DAB", "A123"])
def test_convertion_failure_string(id):  # noqa: ANN001
    with pytest.raises(LegacyAPIException):
        revision_id_to_int(id)


def test_convertion_failure_integer():
    with pytest.raises(TypeError):
        revision_id_to_int(123)
