from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

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

    @staticmethod
    def find_revert_commits(commit_data: list[CommitData]) -> list[str]:
        """Return the full commit messages of any commits that are reverts."""
        revert_commits = []
        for data in commit_data:
            commit_message = data.desc
            if GIT_REVERT_SUMMARY_RE.match(commit_message):
                revert_commits.append(commit_message)
        return revert_commits

    @staticmethod
    def find_reverted_commit_hashes(revert_commit_message: str) -> list[str]:
        """Return the full SHAs named in `This reverts commit <sha>.` lines."""
        return GIT_REVERT_RE.findall(revert_commit_message)
