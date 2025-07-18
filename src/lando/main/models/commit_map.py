import logging
from typing import Self

import requests
import sentry_sdk
from django.db import models

from lando.main.models import BaseModel
from lando.main.models.repo import Repo
from lando.main.scm.consts import SCM_TYPE_GIT, SCM_TYPE_HG

logger = logging.getLogger(__name__)


class CommitMap(BaseModel):
    """Map a git hash to an hg hash, based on a specific repo."""

    HGMO_PUSHLOG_TEMPLATE = "https://hg.mozilla.org/{}/json-pushes"
    # The REPO_MAPPING is used to determine which HgMO repo to inspect when
    # looking for new commits for a given Git repo.
    # Tuples of (Git, HgMO) repository names.
    # Use what Repo.git_commit_map() would return as the Git name.
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

    @classmethod
    def git2hg(cls, git_repo_name: str, commit_hash: str) -> str:
        """Return Hg hash for the given repo and Git hash."""
        map = cls.map_hash_from(SCM_TYPE_GIT, git_repo_name, commit_hash)
        return map.hg_hash

    @classmethod
    def hg2git(cls, git_repo_name: str, commit_hash: str) -> str:
        """Return Git hash for the given repo and Hg hash."""
        map = cls.map_hash_from(SCM_TYPE_HG, git_repo_name, commit_hash)
        return map.git_hash

    @classmethod
    def map_hash_from(
        cls, src_scm: str, git_repo_name: str, src_commit_hash: str
    ) -> Self:
        """Return destination hash for the given repo and source (SCM_TYPE_*) hash.

        This method can raise CommitMap.DoesNotExist.
        """
        hash_field = f"{src_scm}_hash"

        filters = {hash_field: src_commit_hash, "git_repo_name": git_repo_name}
        commit_query = CommitMap.objects.filter(**filters)

        if not commit_query.exists():
            cls.catch_up(git_repo_name)

        # At the moment, we can only have 0 or 1 hit, but this could be different in the
        # future if, e.g., we want to allow partial hash prefixes and return all
        # matching commits.
        return commit_query.get()

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
        response = requests.get(url, params=kwargs)
        try:
            response.raise_for_status()
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.warning(f"Cannot fetch pushlog data from {url}: {exc}")
            return {}

        push_data = response.json()

        # We don't care about the key, as it is just the push ID.
        # NOTE: multiple changesets may be included in the response.

        pushes = sorted(push_data.keys())
        for push_id in pushes:
            hg_changesets = push_data[push_id]["changesets"]
            git_changesets = push_data[push_id]["git_changesets"]

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
