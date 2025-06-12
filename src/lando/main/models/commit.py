from django.db import models

from lando.main.models import BaseModel


class CommitMap(BaseModel):
    """Map a git hash to an hg hash, based on a specific repo."""

    REPO_MAPPING = (("firefox", "mozilla-unified"),)

    @classmethod
    def get_hg_repo_name(cls, git_repo_name: str) -> str:
        """Return mapped repo name or  git_repo_name by default."""
        return dict(cls.REPO_MAPPING).get(git_repo_name, git_repo_name)

    @classmethod
    def get_git_repo_name(cls, hg_repo_name: str) -> str:
        """Return mapped repo name or  hg_repo_name by default."""
        return {hg: git for git, hg in cls.REPO_MAPPING.values()}.get(
            hg_repo_name, hg_repo_name
        )

    git_hash = models.CharField(default="")
    hg_hash = models.CharField(default="")
    git_repo_name = models.CharField(default="")

    def serialize(self) -> dict[str, str]:
        return {
            "git_hash": self.git_hash,
            "hg_hash": self.hg_hash,
            "git_repo_name": self.git_repo_name,
        }
