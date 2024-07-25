"""
This module provides the API controllers for the `DiffWarning` model.

These API endpoints can be used by clients (such as Lando UI, Code Review bot, etc.) to
get, create, or archive warnings.
"""

import logging

from lando.api.legacy.decorators import require_phabricator_api_key
from lando.main.models.revision import DiffWarning, DiffWarningStatus
from lando.main.support import problem

logger = logging.getLogger(__name__)


@require_phabricator_api_key(provide_client=False)
def post(data: dict):
    """Create a new `DiffWarning` based on provided revision and diff IDs.

    Args:
        data (dict): A dictionary containing data to store in the warning. `data`
            should contain at least a `message` key that contains the message to
            show in the warning.

    Returns:
        dict: a dictionary representation of the object that was created.
    """
    # TODO: validate whether revision/diff exist or not.
    if "message" not in data["data"]:
        return problem(
            400,
            "Provided data is not in correct format",
            "Missing required 'message' key in data",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    warning = DiffWarning(**data)
    warning.save()
    return warning.serialize(), 201


@require_phabricator_api_key(provide_client=False)
def delete(pk: str):
    """Archive a `DiffWarning` based on provided pk."""
    warning = DiffWarning.objects.get(pk=pk)
    if not warning:
        return problem(
            400,
            "DiffWarning does not exist",
            f"DiffWarning with primary key {pk} does not exist",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    warning.status = DiffWarningStatus.ARCHIVED
    warning.save()
    return warning.serialize(), 200


@require_phabricator_api_key(provide_client=False)
def get(revision_id: str, diff_id: str, group: str):
    """Return a list of active revision diff warnings, if any."""
    warnings = DiffWarning.objects.filter(
        revision_id=revision_id,
        diff_id=diff_id,
        status=DiffWarningStatus.ACTIVE,
        group=group,
    )
    return [w.serialize() for w in warnings], 200
