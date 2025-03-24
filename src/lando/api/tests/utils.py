import os


def phab_url(path) -> str:  # noqa: ANN001
    """Utility to generate a url to Phabricator's API"""
    return "%s/api/%s" % (os.getenv("PHABRICATOR_URL"), path)
