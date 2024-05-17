from django.core.management import call_command
from lando.version import version

def test_version():
    # Explicitly generate the version.py file since we can't
    # guarantee it already exists in the testing environment.
    call_command('generate_version_file')

    # Every commit will change the exact version string, so it
    # doesn't make sense to compare it against a known value.
    # Testing that it exists, is a string, and is at least 5
    # characters long (eg: "1.1.1") should suffice.
    assert version is not None, "'version' should not be None"
    assert isinstance(version, str), "'version' should be a string"
    assert len(version) >= 5, "'version' string should be at least 5 characters long"
