import logging

from django.core.validators import (
    MaxLengthValidator,
    MinLengthValidator,
    RegexValidator,
)
from django.db import models

from lando.main.models import Repo

# We need to import from the specific file to avoid dependency loops.
from lando.main.scm.commit import CommitData

from .consts import COMMIT_ID_HEX_LENGTH, MAX_FILENAME_LENGTH, MAX_PATH_LENGTH

logger = logging.getLogger(__name__)


class File(models.Model):
    """A file in a repository.

    Files get associated to the Commits that modify them.
    """

    name = models.CharField(max_length=MAX_PATH_LENGTH)

    repo = models.ForeignKey(
        Repo,
        null=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        unique_together = ("repo", "name")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(repo={self.repo!r}, name={self.name})"

    def __str__(self) -> str:
        return f"File {self.name} in {self.repo}"


class Commit(models.Model):
    """An SCM commit.

    They hold all the commit metadata, as well as DAG relationship to other commits, and
    lists of modified files. They get aggregated in Pushes.
    """

    hash = models.CharField(
        max_length=COMMIT_ID_HEX_LENGTH,
        db_index=True,
        blank=False,
        validators=[
            MaxLengthValidator(COMMIT_ID_HEX_LENGTH),
            MinLengthValidator(COMMIT_ID_HEX_LENGTH),
            RegexValidator(r"^([a-fA-F0-9])+"),
        ],
    )

    repo = models.ForeignKey(
        Repo,
        null=True,
        on_delete=models.SET_NULL,
    )

    # Assuming a max email address length (see Push model), and then some space for a long name.
    # XXX: Should we have a separate table?
    author = models.CharField(
        max_length=512,
        db_index=True,
    )

    datetime = models.DateTimeField(
        auto_now=False,
        auto_now_add=False,
        db_index=True,
    )

    desc = models.TextField()

    _files = models.ManyToManyField(File, db_column="files")
    _unsaved_files: set[str]

    _parents = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="descendants",
        db_column="parent",
    )
    _unsaved_parents: set[str]

    class Meta:
        # We want to order commits by ascending IDs. This assumes that commits are added
        # to the PushLog following the dag from earliest to latest.
        ordering = ["id"]
        get_latest_by = "id"
        unique_together = ("repo", "hash")

    def __init__(self, *args, **kwargs):
        self._unsaved_parents = set()
        if "parents" in kwargs:
            self.add_parents(kwargs["parents"])
            del kwargs["parents"]

        self._unsaved_files = set()
        if "files" in kwargs:
            self.add_files(kwargs["files"])
            del kwargs["files"]

        super(Commit, self).__init__(*args, **kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(repo={self.repo!r}, hash={self.hash})"

    def __str__(self) -> str:
        return f"Commit {self.hash} in {self.repo}"

    @staticmethod
    def from_scm_commit(repo: Repo, scm_commit: CommitData):  # noqa: ANN205
        """Create a Commit ORM object from an Commit dataclass."""
        try:
            # If a commit already exists in the DB, don't create a new one.
            return Commit.objects.get(repo=repo, hash=scm_commit.hash)
        except Commit.DoesNotExist:
            pass

        return Commit(
            repo=repo,
            hash=scm_commit.hash,
            author=scm_commit.author,
            datetime=scm_commit.datetime,
            desc=scm_commit.desc,
            parents=scm_commit.parents,
            files=scm_commit.files,
        )

    def save(self, *args, **kwargs):
        """Save the Commit data to the DB.

        If any parent commits or files have been added, this method will find or create
        them as needed, and maintain the DB relations.
        """
        # First make sure we don't deal with stale data.
        try:
            self.refresh_from_db()
        except Commit.DoesNotExist:
            # We're OK if this commit doesn't exist in the DB yet; we're just about to
            # write it.
            pass

        if not self.id and any([self._unsaved_files, self._unsaved_parents]):
            # We need the Commit to exist in the DB before being able to associate
            # parents or files to it.
            super(Commit, self).save(*args, **kwargs)

        if self._unsaved_parents:
            while self._unsaved_parents:
                # XXX: Should we do a single query, then set comparison to see if elements are
                # missing?
                parent_hash = self._unsaved_parents.pop()

                try:
                    parent_commit = Commit.objects.get(repo=self.repo, hash=parent_hash)
                except Commit.DoesNotExist:
                    # XXX: This MUST be an exception, but it's problematic for
                    # pre-existing repos with un-imported history.
                    # raise Commit.DoesNotExist(
                    logger.error(
                        f"Parent commit not found for repo. commit={self.hash} parent_commit={parent_hash} repo={self.repo}"
                    )
                    # ) from e
                else:
                    self._parents.add(parent_commit)

        if self._unsaved_files:
            while self._unsaved_files:
                # XXX: Should we do a single query, then set comparison to see if elements are
                # missing?
                file = File.objects.get_or_create(
                    repo=self.repo, name=self._unsaved_files.pop()
                )[0]
                self._files.add(file)

        super(Commit, self).save(*args, **kwargs)

    @property
    def parents(self) -> list[str]:
        """Return a deduplicated Python list of parent hashes as strings."""
        if self.id:
            # Only query the DB if the object is not new.
            saved_parents = {c.hash for c in self._parents.all()}
            return list(self._unsaved_parents.union(saved_parents))

        return list(self._unsaved_parents)

    def add_parents(self, parents: list[str]):
        """Add parents to this commit.

        We unconditionally add parent hashes, even if they already exist in the DB, but
        the attribute is deduplicated on get.

        There is currently no way to remove a parent.
        """
        self._unsaved_parents.update(parents)

    @property
    def files(self) -> list[str]:
        """Return a deduplicated Python list of file names as strings."""
        if self.id:
            # Only query the DB if the object is not new.
            saved_files = {c.name for c in self._files.all()}
            return list(self._unsaved_files.union(saved_files))

        return list(self._unsaved_files)

    def add_files(self, files: list[str]):
        """Record a list of files as being touched by this commit.

        Existing File objects (by `name`) will be reused, or created otherwise.

        There is currently no way to remove a file.
        """
        self._unsaved_files.update(files)


class Tag(models.Model):
    """A human-readable tag pointing to a Commit."""

    # Tag names are limited by how long a filename the filesystem support.
    name = models.CharField(max_length=MAX_FILENAME_LENGTH)
    commit = models.ForeignKey(Commit, on_delete=models.CASCADE)

    repo = models.ForeignKey(
        Repo,
        null=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        unique_together = ("repo", "name")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(repo={self.repo!r}, name={self.name}, commit={self.commit})"

    def __str__(self) -> str:
        return (
            f"Tag {self.name} in {self.repo.url} pointing to Commit {self.commit.hash}"
        )
