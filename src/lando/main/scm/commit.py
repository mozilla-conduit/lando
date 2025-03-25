from dataclasses import dataclass
from datetime import datetime


@dataclass
class CommitData:
    """A simple dataclass to carry all information related to a commit."""

    hash: str
    parents: list[str]
    author: str
    datetime: datetime
    desc: str
    files: list[str]
