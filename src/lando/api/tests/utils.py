import os


def phab_url(path):
    """Utility to generate a url to Phabricator's API"""
    return "%s/api/%s" % (os.getenv("PHABRICATOR_URL"), path)
