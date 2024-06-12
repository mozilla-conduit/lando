from django.core.management import call_command

import pytest


@pytest.fixture
def lando_version():
    # The version file may or may not exist in the testing environment.
    # We'll explicitly generate it to ensure it's there.
    call_command('generate_version_file')

    try:
        from lando.version import version
        return version
    except ImportError:
        pytest.fail("ImportError: Unable to import the version file after generation.")