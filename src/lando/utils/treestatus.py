from django.conf import settings

from lando.api.legacy.treestatus import (
    TreeStatus,
    TreeStatusCommunicationException,
    TreeStatusError,
)
from lando.treestatus.views.api import TreeData
from lando.version import version


def get_treestatus_client() -> TreeStatus:
    """Returns a TreeStatus client configured for use by Lando."""
    treestatus_client = TreeStatus(url=settings.TREESTATUS_URL)
    treestatus_client.session.headers.update(
        {"User-Agent": f"landoapi.treestatus.TreeStatus/{version}"}
    )
    return treestatus_client


def get_treestatus_data(tree: str) -> TreeData | dict[str, str]:
    """Return TreeStatus data for the given tree.

    Returns:
        TreeData: a well-formed Tree status data

        or

        dict: a simple error dict, with `reason`, `status` and `tree` keys;
        suitable for formatting via lando.jinja.treestatus_to_status_badge_class.

    """
    ts_client = get_treestatus_client()
    try:
        return TreeData(**ts_client.get_trees(tree)["result"])
    except (TreeStatusCommunicationException, TreeStatusError) as exc:
        return {
            "reason": f"{exc.__class__.__name__}: {exc}",
            "status": "unknown",
            "tree": tree,
        }
