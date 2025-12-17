import re

from lando.main.support import LegacyAPIException

REVISION_ID_RE = re.compile(r"^D(?P<id>[1-9][0-9]*)$")


def revision_id_to_int(revision_id: str) -> int:
    m = REVISION_ID_RE.match(revision_id)
    if m is None:
        raise LegacyAPIException(
            400,
            'Revision IDs must be of the form "D<integer>"',
        )

    return int(m.group("id"))


def parse_landing_path(landing_path: list[dict]) -> list[tuple[int, int]]:
    """Convert a list of landing path dicts with `str` values into a list of int tuples."""
    try:
        return [
            (revision_id_to_int(item["revision_id"]), int(item["diff_id"]))
            for item in landing_path
        ]
    except (ValueError, TypeError, KeyError) as e:
        raise LegacyAPIException(
            400,
            f"The provided landing_path was malformed.\n{str(e)}",
        )


def parse_revision_ids(revision_ids_str: str) -> list[int]:
    """Parse comma-separated revision IDs into a list of integers.

    Args:
        revision_ids_str: A string containing comma-separated revision IDs.

    Returns:
        A list of integer revision IDs.

    Raises:
        ValueError: If the string cannot be parsed as comma-separated integers
                   or if the string is empty/whitespace only.

    Examples:
        >>> parse_revision_ids("1234,5678")
        [1234, 5678]
        >>> parse_revision_ids("1234, 5678, 9012")
        [1234, 5678, 9012]
        >>> parse_revision_ids("  1234  ,  5678  ")
        [1234, 5678]
        >>> parse_revision_ids("")
        Traceback (most recent call last):
            ...
        ValueError: At least one revision ID is required.
    """
    if not revision_ids_str or not revision_ids_str.strip():
        raise ValueError("At least one revision ID is required.")

    try:
        revision_ids = [
            int(rev_id.strip())
            for rev_id in revision_ids_str.split(",")
            if rev_id.strip()
        ]
    except ValueError as e:
        raise ValueError(
            "Invalid revision IDs. Must be comma-separated integers."
        ) from e

    if not revision_ids:
        raise ValueError("At least one revision ID is required.")

    return revision_ids
