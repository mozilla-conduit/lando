import pytest

from lando.version import version


@pytest.fixture
def lando_version():
    return version
