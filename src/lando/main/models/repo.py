import logging
import os
import subprocess
import tempfile
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
    HgSCM,
)
from lando.utils import GitPatchHelper

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
    default_branch = models.CharField(max_length=255, default="main")
    scm_type = models.CharField(
        max_length=3,
        choices=SCM_TYPE_CHOICES,
        null=True,
        blank=True,
        default=None,
    )
    is_initialized = models.BooleanField(default=False)

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
            models.CharField(max_length=32, blank=True),
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

    @classmethod
    def get_mapping(cls) -> dict[str, "Repo"]:
        return {repo.tree: repo for repo in cls.objects.all()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def scm(self) -> AbstractSCM:
        """Return the SCM implementation associated with this Repository"""
        if not self._scm:
            if self.scm_type == SCM_TYPE_HG:
                self._scm = HgSCM(self.path)
            else:
                raise Exception(f"Repository type not supported: {self.scm_type}")
        return self._scm

    def __str__(self):
        return f"{self.name} ({self.default_branch})"

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

        A fallback is in place for SCM_TYPE_GIT, which is not yet part of the SCM_IMPLEMENTATIONS.
        """
        for scm, impl in SCM_IMPLEMENTATIONS.items():
            if impl.repo_is_supported(pull_path):
                return scm
        if self._is_git_repo:
            return SCM_TYPE_GIT
        raise ValueError(f"Could not determine repo type for {pull_path}")

    @property
    def is_git_repo(self):
        return self.scm_type is not None and self.scm_type == SCM_TYPE_GIT

    @property
    def _is_git_repo(self):
        command = ["git", "ls-remote", self.pull_path]
        returncode = subprocess.call(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return not returncode

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

    def _git_run(self, *args, cwd=None):
        cwd = cwd or self.system_path
        command = ["git"] + list(args)
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        return result

    def _git_initialize(self):
        self.refresh_from_db()

        if self.is_initialized:
            raise

        self.system_path = str(Path(settings.REPO_ROOT) / self.name)
        result = self._git_run(
            "clone", self.pull_path, self.name, cwd=settings.REPO_ROOT
        )
        if result.returncode == 0:
            self.is_initialized = True
            self.save()
        else:
            raise Exception(f"{result.returncode}: {result.stderr}")

    def _git_pull(self):
        self._git_run("pull", "--all", "--prune")

    def _git_reset(self, branch=None):
        self._git_run("reset", "--hard", branch or self.default_branch)
        self._git_run("clean", "--force")

    def _git_apply_patch(self, patch_buffer: str):
        patch_helper = GitPatchHelper(patch_buffer)
        self.patch_header = patch_helper.get_header

        # Import the diff to apply the changes then commit separately to
        # ensure correct parsing of the commit message.
        f_msg = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        f_diff = tempfile.NamedTemporaryFile(encoding="utf-8", mode="w+")
        with f_msg, f_diff:
            patch_helper.write_commit_description(f_msg)
            f_msg.flush()
            patch_helper.write_diff(f_diff)
            f_diff.flush()

            self._git_run("apply", f_diff.name)

            # Commit using the extracted date, user, and commit desc.
            # --landing_system is provided by the set_landing_system hgext.
            date = patch_helper.get_header("Date")
            user = patch_helper.get_header("From")

            self._git_run("add", "-A")
            self._git_run(
                "commit", "--date", date, "--author", user, "--file", f_msg.name
            )

    def _git_last_commit_id(self) -> str:
        return self._git_run("rev-parse", "HEAD").stdout.strip()

    def _git_push(self):
        self._git_run("push")
