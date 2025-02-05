import logging
import os

from django.db import models

from lando.main.models import BaseModel, Repo
from lando.main.scm import SCM_TYPE_CHOICES, SCM_TYPE_HG

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class Worker(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    is_paused = models.BooleanField(default=False)
    is_stopped = models.BooleanField(default=False)
    applicable_repos = models.ManyToManyField(Repo)

    throttle_seconds = models.IntegerField(default=10)
    sleep_seconds = models.IntegerField(default=10)

    scm = models.CharField(
        max_length=3,
        choices=SCM_TYPE_CHOICES,
        default=SCM_TYPE_HG,
    )

    def __str__(self):
        if self.is_stopped:
            state = "STOPPED"
        elif self.is_paused:
            state = "PAUSED"
        else:
            state = "RUNNING"

        repo_count = self.enabled_repos.count()
        name = self.name
        return f"{name} [{state}] [{repo_count} repos]"

    @property
    def enabled_repos(self) -> list[Repo]:
        return self.applicable_repos.all()

    @property
    def enabled_repo_names(self) -> list[str]:
        return self.enabled_repos.values_list("name", flat=True)
