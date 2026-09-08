import re
from dataclasses import dataclass
from datetime import datetime

from lando.api.legacy.commit_message import parse_bugs

GIT_REVERT_SUMMARY_RE = re.compile(r"^Revert \"?(?P<summary>.*)\"?")
GIT_REVERT_RE = re.compile(r"This reverts commit (?P<commit>[0-9a-f]{40})")


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

    @staticmethod
    def find_revert_commits(commit_data: list[CommitData]) -> list[CommitData]:
        """Return any commits that are reverts."""
        return [commit for commit in commit_data if commit.is_revert_commit()]

    def is_revert_commit(self) -> bool:
        """Return whether this commit's message marks it as a revert."""
        return bool(GIT_REVERT_SUMMARY_RE.match(self.desc))

    def reverted_commit_hashes(self) -> list[str]:
        """Return the full SHAs this commit reverts."""
        return GIT_REVERT_RE.findall(self.desc)
