from django.db import models

from lando.main.models import Repo

from .commit import Commit
from .consts import MAX_FILENAME_LENGTH

PUSH_SCM_TYPE_GIT = "git"
PUSH_SCM_TYPES = [PUSH_SCM_TYPE_GIT]


class Push(models.Model):
    push_id = models.PositiveIntegerField()

    repo = models.ForeignKey(
        Repo,
        # We don't want to delete the PushLog, even if we were to delete the repo
        # object.
        on_delete=models.DO_NOTHING,
    )

    date = models.DateField(
        auto_now=False,
        auto_now_add=True,
        db_index=True,
    )

    # Maximum total lengths are defined in RFC-5321 [0]: 64 for the local-part, and 255
    # for the domain.
    # [0] https://datatracker.ietf.org/doc/html/rfc5321#section-4.5.3.1.1
    user = models.EmailField(max_length=64 + 1 + 255)

    commits = models.ManyToManyField(Commit)

    # Branch names are limited by how long a filename the filesystem support. This is
    # generally 255 bytes.
    branch = models.CharField(max_length=MAX_FILENAME_LENGTH)

    class Meta:
        unique_together = ("push_id", "repo")

    def __repr__(self):
        return f"<{self.__class__.__name__}({self.push_id } on {self.repo})>"

    def save(self, *args, **kwargs):
        if not self.id:
            # Determine the next push_id on first save
            next_push_id = self._next_push_id(self.repo)
            self.push_id = next_push_id
        super(Push, self).save(*args, **kwargs)

    @classmethod
    def _next_push_id(cls, repo: Repo):
        """Generate a monotonically increasing sequence of push_id, scoped by Repo."""
        max_push_id = (
            cls.objects.filter(repo=repo)
            .order_by("-push_id")
            .values_list("push_id", flat=True)
        )

        if max_push_id:
            return max_push_id[0] + 1

        return 1
