import pytest
from django.core.management import call_command


@pytest.fixture
def lando_version():  # noqa: ANN201
    # The version file may or may not exist in the testing environment.
    # We'll explicitly generate it to ensure it's there.
    call_command("generate_version_file")

    from lando.version import version

    return version
