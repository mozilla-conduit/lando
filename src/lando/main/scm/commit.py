from dataclasses import dataclass
from datetime import datetime

from lando.api.legacy.commit_message import parse_bugs


@dataclass
class CommitData:
    """A simple dataclass to carry all information related to a commit."""

    hash: str
    parents: list[str]
    author: str
    datetime: datetime
    desc: str
    files: list[str]

    @property
    def bug_ids(self) -> list[str]:
        """Bug IDs referenced by the first line of the commit message."""
        title = self.desc.splitlines()[0] if self.desc else ""
        return [str(bug) for bug in parse_bugs(title)]
