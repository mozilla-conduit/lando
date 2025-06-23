import requests
from django.db import models

from lando.main.models import BaseModel
from lando.main.models.repo import Repo


class CommitMap(BaseModel):
    """Map a git hash to an hg hash, based on a specific repo."""

    HGMO_PUSHLOG_TEMPLATE = "https://hg.mozilla.org/{}/json-pushes"
    REPO_MAPPING = (("firefox", "mozilla-unified"),)

    git_hash = models.CharField(default="", max_length=40)
    hg_hash = models.CharField(default="", max_length=40)

    # NOTE: This value is set because multiple Lando repos can map to a single hg repo.
    # This is because currently a separate repo object is created for each branch of a
    # git repo, though those might map to a single hg repo (e.g., mozilla-unified).
    git_repo_name = models.CharField(default="")

    class Meta:
        unique_together = (
            ("git_repo_name", "git_hash"),
            ("git_repo_name", "hg_hash"),
        )

    @classmethod
    def get_hg_repo_name(cls, git_repo_name: str) -> str:
        """Return mapped repo name or `git_repo_name` by default."""
        return dict(cls.REPO_MAPPING).get(git_repo_name, git_repo_name)

    @classmethod
    def get_git_repo_name(cls, hg_repo_name: str) -> str:
        """Return mapped repo name or `hg_repo_name` by default."""
        return {hg: git for git, hg in cls.REPO_MAPPING}.get(hg_repo_name, hg_repo_name)

    @classmethod
    def get_pushlog_url(cls, git_repo_name: str) -> str:
        """Return pushlog URL based on provided repo name."""
        return cls.HGMO_PUSHLOG_TEMPLATE.format(cls.get_hg_repo_name(git_repo_name))

    @classmethod
    def _find_last_node(cls, git_repo_name: str) -> "CommitMap":
        """Return last CommitMap object that was stored for given repo."""
        return cls.objects.filter(git_repo_name=git_repo_name).latest("created_at")

    @classmethod
    def find_last_hg_node(cls, git_repo_name: Repo) -> str:
        """Return hg hash of last CommitMap object for given repo."""
        return cls._find_last_node(git_repo_name).hg_hash

    def serialize(self) -> dict[str, str]:
        """Return a simple dictionary containing the git and hg hashes."""
        return {
            "git_hash": self.git_hash,
            "hg_hash": self.hg_hash,
        }

    @classmethod
    def catch_up(cls, git_repo_name: str):
        """Find the last stored commit hash and query the pushlog."""
        commit_hash = cls.find_last_hg_node(git_repo_name)
        cls.fetch_push_data(
            git_repo_name=git_repo_name,
            fromchangeset=commit_hash,
        )

    @classmethod
    def fetch_push_data(cls, git_repo_name: str, **kwargs) -> dict:
        """Query the pushlog and create corresponding CommitMap objects."""
        url = cls.get_pushlog_url(git_repo_name)
        push_data = requests.get(url, params=kwargs).json()

        # We don't care about the key, as it is just the push ID.
        # NOTE: multiple changesets may be included in the response.
        for push in list(push_data.values()):
            hg_changesets = push["changesets"]
            git_changesets = push["git_changesets"]

            if len(hg_changesets) != len(git_changesets):
                raise ValueError(
                    "Number of hg changesets does not match number of git changesets: "
                    f"{len(hg_changesets)} vs {len(git_changesets)}"
                )

            for hg_changeset, git_changeset in zip(
                hg_changesets, git_changesets, strict=True
            ):
                params = {
                    "hg_hash": hg_changeset,
                    "git_hash": git_changeset,
                    "git_repo_name": git_repo_name,
                }
                if not cls.objects.filter(**params).exists():
                    cls.objects.create(**params)
