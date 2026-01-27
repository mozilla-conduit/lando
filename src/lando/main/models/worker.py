import logging

from django.db import ProgrammingError, models
from django.utils.translation import gettext_lazy

from lando.main.models.base import BaseModel
from lando.main.models.repo import Repo
from lando.main.scm import SCMType

logger = logging.getLogger(__name__)


class WorkerType(models.TextChoices):
    """A TextChoices allowing to differentiate worker types in models and input."""

    LANDING = "LANDING", gettext_lazy("Landing worker")
    AUTOMATION = "AUTOMATION", gettext_lazy("Automation worker")
    UPLIFT = "UPLIFT", gettext_lazy("Uplift worker")


class Worker(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    is_paused = models.BooleanField(default=False)
    is_stopped = models.BooleanField(default=False)
    applicable_repos = models.ManyToManyField(Repo)

    throttle_seconds = models.IntegerField(default=10)
    sleep_seconds = models.IntegerField(default=10)

    type = models.CharField(
        choices=WorkerType,
        default=WorkerType.LANDING,
    )

    scm = models.CharField(
        max_length=3,
        choices=SCMType,
        default=SCMType.HG,
    )

    def __str__(self) -> str:
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

    def save_or_update(self, is_paused: bool):
        """Change the value of is_paused via a save or update."""
        self.is_paused = is_paused
        try:
            self.save()
        except ProgrammingError as e:
            # In some cases (e.g., during maintenance command), database migrations
            # may cause self.save() to fail. Try again using an update, and log error.
            logger.error(e)
            logger.warning(f"{self} was paused using an update instead of save.")
            Worker.objects.filter(pk=self.pk).update(is_paused=True)

    def pause(self):
        """Pause the landing worker if it is not already paused."""
        if not self.is_paused:
            self.save_or_update(is_paused=True)

    def resume(self):
        """Resume the landing worker if it is paused."""
        if self.is_paused:
            self.save_or_update(is_paused=False)
