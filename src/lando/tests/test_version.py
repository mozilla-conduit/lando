def test_version(lando_version):
    # Every commit will change the exact version string, so it
    # doesn't make sense to compare it against a known value.
    # Testing that it exists, is a string, and is at least 5
    # characters long (eg: "1.1.1") should suffice.
    assert lando_version is not None, "'version' should not be None"
    assert isinstance(lando_version, str), "'version' should be a string"
    assert len(lando_version) >= 5, "'version' string should be at least 5 characters long"
