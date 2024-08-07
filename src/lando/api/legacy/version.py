import json
import logging
import os

logger = logging.getLogger(__name__)


def version() -> dict[str, str]:
    version = {
        "source": "https://github.com/mozilla-conduit/lando-api",
        "version": "0.0.0",
        "commit": "",
        "build": "dev",
    }

    # Read the version information.
    path = os.getenv("VERSION_PATH", "/app/version.json")
    try:
        with open(path) as f:
            version = json.load(f)
    except (IOError, ValueError):
        logger.warning(f"version file ({path}) could not be loaded, assuming dev")

    return version
