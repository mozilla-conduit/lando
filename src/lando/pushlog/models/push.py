from django.db import models

from lando.main.models import Repo

from .commit import Commit
from .consts import MAX_BRANCH_LENGTH, MAX_URL_LENGTH

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

    # Full URL to the upstream repository, to allow re-linking the data if anything goes
    # wrong in the DB.
    repo_url = models.CharField(max_length=MAX_URL_LENGTH, db_index=True)

    # Branch names are limited by how long a filename the filesystem support.
    branch = models.CharField(max_length=MAX_BRANCH_LENGTH, db_index=True)

    date = models.DateTimeField(
        auto_now=False,
        auto_now_add=True,
        db_index=True,
    )

    # Maximum total lengths are defined in RFC-5321 [0]: 64 for the local-part, and 255
    # for the domain.
    # [0] https://datatracker.ietf.org/doc/html/rfc5321#section-4.5.3.1.1
    user = models.EmailField(max_length=64 + 1 + 255)

    commits = models.ManyToManyField(Commit)

    class Meta:
        unique_together = ("push_id", "repo")

    def __repr__(self):
        return f"{self.__class__.__name__}(push_id={self.push_id}, repo={self.repo})"

    def __str__(self):
        ncommits = self.commits.count()
        plural = "s" if ncommits > 1 else ""
        return f"Push {self.push_id} to {self.repo_url} by {self.user} on {self.date} with {ncommits} commit{plural}"

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
