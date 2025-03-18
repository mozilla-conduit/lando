import logging
import os
import urllib
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

from lando.main.models import BaseModel
from lando.main.scm import (
    SCM_IMPLEMENTATIONS,
    SCM_TYPE_CHOICES,
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
    AbstractSCM,
)

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))

# DONTBUILD flag and help text.
DONTBUILD = (
    "DONTBUILD",
    (
        "Should be used only for trivial changes (typo, comment changes,"
        " documentation changes, etc.) where the risk of introducing a"
        " new bug is close to none."
    ),
)


def validate_path_in_repo_root(value: str):
    path = Path(value)
    if path.parent != Path(settings.REPO_ROOT):
        raise ValidationError(
            f"Path {path} must be a direct child of {settings.REPO_ROOT}."
        )


class RepoError(Exception):
    """An exception that is raised when there is a fatal repository related issue."""

    pass


class Repo(BaseModel):
    """Represents the configuration of a particular repo."""

    _scm: Optional[AbstractSCM] = None

    @property
    def path(self) -> str:
        return str(self.system_path) or self.get_system_path()

    # TODO: help text for fields below.
    name = models.CharField(max_length=255, unique=True)
    default_branch = models.CharField(max_length=255, default="", blank=True)
    scm_type = models.CharField(
        max_length=3,
        choices=SCM_TYPE_CHOICES,
        null=True,
        blank=True,
        default=None,
    )
    system_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        validators=[validate_path_in_repo_root],
    )

    # Legacy fields. These fields were adapted from the legacy implementation of Lando.
    pull_path = models.CharField(blank=True)
    push_path = models.CharField(blank=True)
    required_permission = models.CharField(default="")
    short_name = models.CharField(blank=True)
    url = models.CharField()

    approval_required = models.BooleanField(default=False)
    autoformat_enabled = models.BooleanField(default=False)
    commit_flags = ArrayField(
        ArrayField(
            models.CharField(max_length=100, blank=True),
        ),
        size=2,
        blank=True,
        null=True,
        default=None,
    )
    force_push = models.BooleanField(default=False)
    is_phabricator_repo = models.BooleanField(default=True)
    milestone_tracking_flag_template = models.CharField(blank=True, default="")
    product_details_url = models.CharField(blank=True, default="")

    # Ideally, we'd like the push_target to be nullable, but Django forms will not
    # honour this, and instead put an empty string when blankable fields are left empty.
    # We handle the case later in the code (namely in HgSCM.push), by treating the empty
    # string as falsey.
    push_target = models.CharField(blank=True, default="")

    # If this repo was migrated from another repo, link to it here.
    # If this value is set, then revisions targeting legacy_source will
    # have their target repo switched to `self` upon triggering a landing.

    # For example, if `self` is `NewGitRepo` and `self.legacy_source` is `OldHgRepo`
    # then:
    # - `NewGitRepo.is_legacy` is False
    # - `OldHgRepo.is_legacy` is True
    # - `NewGitRepo.target_repo` is not defined
    # - `OldHgRepo.target_repo` is set to `NewGitRepo`
    # A revision that was created against `OldHgRepo` will land in `NewGitRepo`.
    legacy_source = models.OneToOneField(
        "Repo",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="new_target",
    )

    @property
    def is_legacy(self):
        """Return True if this repo is listed as a legacy source."""
        try:
            return self.new_target is not None
        except self.DoesNotExist:
            return False

    @property
    def is_git(self):
        return self.scm_type == SCM_TYPE_GIT

    @property
    def is_hg(self):
        return self.scm_type == SCM_TYPE_HG

    def __str__(self):
        if self.is_git:
            return f"{self.name}@{self.default_branch} ({self.scm_type})"
        return f"{self.name} ({self.scm_type})"

    @classmethod
    def get_mapping(cls) -> dict[str, "Repo"]:
        return {repo.short_name: repo for repo in cls.objects.all()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def scm(self) -> AbstractSCM:
        """Return the SCM implementation associated with this Repository"""
        if not self._scm:
            if impl := SCM_IMPLEMENTATIONS.get(self.scm_type):
                self._scm = impl(self.path)
            else:
                raise Exception(f"Repository type not supported: {self.scm_type}")
        return self._scm

    def get_system_path(self) -> str:
        """Calculate system path based on REPO_ROOT and repository name."""
        return str(Path(settings.REPO_ROOT) / self.name)

    @property
    def _method_not_supported_for_repo_error(self) -> RepoError:
        return RepoError(f"Method is not supported for {self}")

    def raise_for_unsupported_repo_scm(self, supported_scm: str):
        """Raise a RepoError if the repo SCM does not match the supported SCM."""
        if supported_scm != self.scm_type:
            raise self._method_not_supported_for_repo_error

    def save(self, *args, **kwargs):
        """Determine values for various fields upon saving the instance."""
        if not self.system_path:
            self.system_path = self.get_system_path()

        if not self.push_path or not self.pull_path:
            url = urllib.parse.urlparse(self.url)
            if not self.push_path:
                self.push_path = f"ssh://{url.netloc}{url.path}"
            if not self.pull_path:
                self.pull_path = self.url

        if not self.short_name:
            self.short_name = self.tree

        if not self.commit_flags:
            self.commit_flags = []

        if not self.scm_type:
            self.scm_type = self._find_supporting_scm(self.pull_path)

        super().save(*args, **kwargs)

    def _find_supporting_scm(self, pull_path: str) -> str:
        """Loop through the supported SCM_IMPLEMENTATIONS and return a key representing
        the first SCM claiming to support the given pull_path.
        """
        for scm, impl in SCM_IMPLEMENTATIONS.items():
            if impl.repo_is_supported(pull_path):
                return scm
        raise ValueError(f"Could not determine repo type for {pull_path}")

    @property
    def tree(self):
        """Backwards-compatibility alias for tree name."""
        return self.name

    @property
    def access_group(self):
        """Temporary property until all usages are ported."""
        raise NotImplementedError(
            "This field has been replaced by `required_permission`"
        )

    @property
    def phab_identifier(self) -> str | None:
        """Return a valid Phabricator identifier as a `str`. Legacy field."""
        if not self.is_phabricator_repo:
            return None

        return self.short_name if self.short_name else self.tree
