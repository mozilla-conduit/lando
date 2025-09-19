from django.db import models

from lando.main.models.landing_job import LandingJob
from lando.main.scm import SCM_TYPE_CHOICES


class TryJob(LandingJob):
    """Represent a Try job."""

    type = "Try"

    class PatchFormat(models.TextChoices):
        GIT_FORMAT_PATCH = "git-format-patch"
        HGEXPORT = "hgexport"

    base_commit_vcs = models.CharField(
        max_length=3,
        choices=SCM_TYPE_CHOICES,
        null=True,
        blank=True,
        default=None,
        help_text="The VCS that the `target_commit_hash` is based on.",
    )

    patch_format = models.CharField(
        max_length=16,
        choices=PatchFormat,
        default=PatchFormat.GIT_FORMAT_PATCH,
        help_text="The format of the patches stored as Revisions.",
    )
