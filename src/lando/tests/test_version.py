from django.conf import settings
from django.core.management import call_command

import pytest

def test_version():
    # The version file may or may not exist in the testing environment.
    # We'll explicitly remove it so that we're in a known state, then
    # re-generate it and test against it.
    version_file = settings.BASE_DIR / "version.py"
    version_file.unlink(missing_ok=True)

    # We should not be able to import it after it's been removed.
    with pytest.raises(ImportError):
        from lando.version import version

    call_command('generate_version_file')

    try:
        from lando.version import version
    except ImportError:
        pytest.fail("ImportError: Unable to import the version file after re-generation.")

    # Every commit will change the exact version string, so it
    # doesn't make sense to compare it against a known value.
    # Testing that it exists, is a string, and is at least 5
    # characters long (eg: "1.1.1") should suffice.
    assert version is not None, "'version' should not be None"
    assert isinstance(version, str), "'version' should be a string"
    assert len(version) >= 5, "'version' string should be at least 5 characters long"
