from django.core.validators import (
    MaxLengthValidator,
    MinLengthValidator,
    RegexValidator,
)
from django.db import models

from lando.main.models import Repo

from .consts import COMMIT_ID_HEX_LENGTH, MAX_FILENAME_LENGTH, MAX_PATH_LENGTH


class File(models.Model):
    name = models.CharField(max_length=MAX_PATH_LENGTH)

    repo = models.ForeignKey(
        Repo,
        # We don't want to delete the PushLog, even if we were to delete the repo
        # object.
        on_delete=models.DO_NOTHING,
    )

    class Meta:
        unique_together = ("repo", "name")

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.repo}, {self.name}) [{self.id}]>"


class Commit(models.Model):
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
        # We don't want to delete the PushLog, even if we were to delete the repo
        # object.
        on_delete=models.DO_NOTHING,
    )

    # Assuming a max email address length (see Push model), and then some space for a long name.
    # XXX: Should we have a separate table?
    author = models.CharField(
        max_length=512,
        db_index=True,
    )

    date = models.DateField(
        auto_now=False,
        auto_now_add=False,
        db_index=True,
    )

    desc = models.TextField()

    files = models.ManyToManyField(File)

    parents = models.ManyToManyField("self", blank=True)

    class Meta:
        unique_together = ("repo", "hash")

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.repo}, {self.hash}) [{self.id}]>"

    def add_files(self, files: list[str]):
        """Record a list of files as being touched by this commit.

        Existing File objects (by `name`) will be reused, or created otherwise.
        """
        files_set = set(files)
        files_from_db = File.objects.filter(repo=self.repo, name__in=files)

        # Associate existing file entries.
        for file in files_from_db:
            self.files.add(file)
            files_set.remove(file.name)

        # Create new ones.
        for filename in files_set:
            # Create and save the object in one action.
            file = File.objects.create(repo=self.repo, name=filename)
            self.files.add(file)


class Tag(models.Model):
    # Tag names are limited by how long a filename the filesystem support.
    name = models.CharField(max_length=MAX_FILENAME_LENGTH)
    commit = models.ForeignKey(Commit, on_delete=models.CASCADE)

    repo = models.ForeignKey(
        Repo,
        # We don't want to delete the PushLog, even if we were to delete the repo
        # object.
        on_delete=models.DO_NOTHING,
    )

    class Meta:
        unique_together = ("repo", "name")

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.repo}, {self.name}, {self.commit}) [{self.id}]>"
