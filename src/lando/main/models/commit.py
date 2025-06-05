from django.db import models

from lando.main.models import BaseModel, Repo


class CommitMap(BaseModel):
    """Map a git hash to an hg hash, based on a specific repo."""

    git_hash = models.CharField(default="")
    hg_hash = models.CharField(default="")
    git_repo = models.ForeignKey(Repo, on_delete=models.DO_NOTHING)

    def serialize(self) -> dict[str, str]:
        return {
            "git_hash": self.git_hash,
            "hg_hash": self.hg_hash,
            "repo_name": self.git_repo.name,
        }
