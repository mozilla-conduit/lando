from django.contrib.postgres.fields import ArrayField
from django.core.validators import (
    MaxLengthValidator,
    MinLengthValidator,
    RegexValidator,
)
from django.db import models

from lando.main.models import (
    BaseJob,
)
from lando.main.scm import COMMIT_ID_HEX_LENGTH, SCM_TYPE_CHOICES


class TryJob(BaseJob):
    """Represent a Try job."""

    type = "Try"

    class PatchFormat(models.TextChoices):
        GIT_FORMAT_PATCH = "git-format-patch"
        HGEXPORT = "hgexport"

    target_commit_hash = models.TextField(
        max_length=40,
        default="",
        help_text="The published base commit on which to apply `patches`.",
        null=False,
        blank=False,
        validators=[
            # XXX: move COMMIT_ID_HEX_LENGTH to scm
            MaxLengthValidator(COMMIT_ID_HEX_LENGTH),
            MinLengthValidator(COMMIT_ID_HEX_LENGTH),
            RegexValidator(r"^([a-fA-F0-9])+"),
        ],
    )

    base_commit_vcs = models.CharField(
        max_length=3,
        choices=SCM_TYPE_CHOICES,
        null=True,
        blank=True,
        default=None,
        help_text="The VCS that the `base_commit` hash is based on.",
    )

    # XXX: We may want to make this a separate table, that we could clear periodically,
    # so we'd retain job information, but not the actual patch data.
    patches = ArrayField(
        models.TextField(
            validators=[
                RegexValidator(r"^[A-Za-z0-9+/]+={0,2}$"),
            ],
        ),
        default=list,
        help_text="Ordered array of base64 encoded patches for submission to Lando.",
    )

    patch_format = models.CharField(
        max_length=16,
        choices=PatchFormat,
        default=PatchFormat.GIT_FORMAT_PATCH,
        help_text="The format of the encoded patches in `patches`.",
    )
