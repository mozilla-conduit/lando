import logging
import os

from django.db import models

from lando.main.models import BaseModel, Repo

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class Worker(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    is_paused = models.BooleanField(default=False)
    is_stopped = models.BooleanField(default=False)
    ssh_private_key = models.TextField(null=True, blank=True)
    applicable_repos = models.ManyToManyField(Repo)

    throttle_seconds = models.IntegerField(default=10)
    sleep_seconds = models.IntegerField(default=10)

    scm = models.CharField(
        max_length=3,
        choices=Repo.SCM_CHOICES,
        default=Repo.HG,
    )

    def __str__(self):
        return self.name

    @property
    def enabled_repos(self) -> list[Repo]:
        return self.applicable_repos.all()

    @property
    def enabled_repo_names(self) -> list[str]:
        return self.enabled_repos.values_list("name", flat=True)
