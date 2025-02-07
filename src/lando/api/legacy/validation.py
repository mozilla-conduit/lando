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
