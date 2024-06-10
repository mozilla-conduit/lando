from django.core.management import call_command

import pytest


@pytest.fixture
def generate_version_file():
    # The version file may or may not exist in the testing environment.
    # We'll explicitly generate it to ensure it's there.
    call_command('generate_version_file')

    try:
        from lando.version import version
    except ImportError:
        pytest.fail("ImportError: Unable to import the version file after generation.")


def test_version(generate_version_file):
    from lando.version import version

    # Every commit will change the exact version string, so it
    # doesn't make sense to compare it against a known value.
    # Testing that it exists, is a string, and is at least 5
    # characters long (eg: "1.1.1") should suffice.
    assert version is not None, "'version' should not be None"
    assert isinstance(version, str), "'version' should be a string"
    assert len(version) >= 5, "'version' string should be at least 5 characters long"
