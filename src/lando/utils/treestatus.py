from django.conf import settings

from lando.api.legacy.treestatus import TreeStatus
from lando.version import version


def getTreestatusClient() -> TreeStatus:
    """Returns a TreeStatus client configured for use by Lando."""
    treestatus_client = TreeStatus(url=settings.TREESTATUS_URL)
    treestatus_client.session.headers.update(
        {"User-Agent": f"landoapi.treestatus.TreeStatus/{version}"}
    )
    return treestatus_client
