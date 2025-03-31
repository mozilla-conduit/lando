from django.db import models

from lando.main.models import Repo

from .commit import Commit
from .consts import MAX_BRANCH_LENGTH, MAX_URL_LENGTH


class Push(models.Model):
    """A Push object records the list of Commits pushed at once."""

    push_id = models.PositiveIntegerField()

    repo = models.ForeignKey(
        Repo,
        null=True,
        on_delete=models.SET_NULL,
    )

    # Full URL to the upstream repository, to allow re-linking the data if anything goes
    # wrong in the DB.
    repo_url = models.CharField(max_length=MAX_URL_LENGTH, db_index=True)

    # Branch names are limited by how long a filename the filesystem support.
    branch = models.CharField(max_length=MAX_BRANCH_LENGTH, db_index=True)

    datetime = models.DateTimeField(
        auto_now=False,
        auto_now_add=True,
        db_index=True,
    )

    # Maximum total lengths are defined in RFC-5321 [0]: 64 for the local-part, and 255
    # for the domain.
    # [0] https://datatracker.ietf.org/doc/html/rfc5321#section-4.5.3.1.1
    user = models.EmailField(max_length=64 + 1 + 255)

    # XXX: We may need to keep a better ordering (rather than relying on DB ordering)
    # via a Through relationship model [0]
    # [0] https://docs.djangoproject.com/en/dev/topics/db/models/#intermediary-manytomany
    commits = models.ManyToManyField(Commit)

    class Meta:
        unique_together = ("push_id", "repo")
        verbose_name_plural = "Pushes"

    def __repr__(self):
        return f"{self.__class__.__name__}(push_id={self.push_id}, repo={self.repo})"

    def __str__(self):
        return f"Push {self.push_id} in {self.repo}"

    def save(self, *args, **kwargs):
        if not self.id:
            # Determine the next push_id on first save
            next_push_id = self._next_push_id(self.repo)
            self.push_id = next_push_id

        if not self.repo_url:
            self.repo_url = self.repo.url
        if not self.branch:
            self.branch = self.repo.default_branch

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
