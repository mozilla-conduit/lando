import logging
import os
import subprocess
import tempfile
import urllib
from pathlib import Path

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from lando.api.legacy.hg import HgRepo
from lando.main.models import BaseModel
from lando.utils import GitPatchHelper

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class RepoError(Exception):
    """An exception that is raised when there is a fatal repository related issue."""

    pass


class Repo(BaseModel):
    """Represents the configuration of a particular repo."""

    HG = "hg"
    GIT = "git"

    SCM_CHOICES = {
        HG: "Mercurial",
        GIT: "Git",
    }

    # TODO: help text for fields below.
    name = models.CharField(max_length=255, unique=True)
    default_branch = models.CharField(max_length=255, default="main")
    scm = models.CharField(
        max_length=3,
        choices=SCM_CHOICES,
        null=True,
        blank=True,
        default=None,
    )
    is_initialized = models.BooleanField(default=False)

    system_path = models.FilePathField(
        path=settings.REPO_ROOT,
        max_length=255,
        allow_folders=True,
        blank=True,
        default="",
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
    push_bookmark = models.CharField(blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_hg_repo:
            self.hg = HgRepo(self.system_path or self.get_system_path())
        else:
            self.hg = None

    def __str__(self):
        return f"{self.name} ({self.default_branch})"

    def get_system_path(self) -> str:
        """Calculate system path based on REPO_ROOT and repository name."""
        return str(Path(settings.REPO_ROOT) / self.name)

    @property
    def _method_not_supported_for_repo_error(self) -> RepoError:
        return RepoError(f"Method is not supported for {self}")

    def raise_for_unsupported_repo_scm(self, repo_scm):
        if repo_scm != self.scm:
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

        if self.scm is None:
            if self._is_git_repo:
                self.scm = self.GIT
            elif self._is_hg_repo:
                self.scm = self.HG
            else:
                raise ValueError("Could not determine repo type.")

        super().save(*args, **kwargs)

    @property
    def is_git_repo(self):
        return self.scm is not None and self.scm == self.GIT

    @property
    def is_hg_repo(self):
        return self.scm is not None and self.scm == self.HG

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
    def _is_hg_repo(self):
        command = ["hg", "identify", self.pull_path]
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

    def _run(self, *args, cwd=None):
        cwd = cwd or self.system_path
        command = ["git"] + list(args)
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        return result

    def initialize(self):
        self.refresh_from_db()

        if self.is_initialized:
            raise

        self.system_path = str(Path(settings.REPO_ROOT) / self.name)
        result = self._run("clone", self.pull_path, self.name, cwd=settings.REPO_ROOT)
        if result.returncode == 0:
            self.is_initialized = True
            self.save()
        else:
            raise Exception(f"{result.returncode}: {result.stderr}")

    def pull(self):
        self._run("pull", "--all", "--prune")

    def reset(self, branch=None):
        self._run("reset", "--hard", branch or self.default_branch)
        self._run("clean", "--force")

    def apply_patch(self, patch_buffer: str):
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

            self._run("apply", f_diff.name)

            # Commit using the extracted date, user, and commit desc.
            # --landing_system is provided by the set_landing_system hgext.
            date = patch_helper.get_header("Date")
            user = patch_helper.get_header("From")

            self._run("add", "-A")
            self._run("commit", "--date", date, "--author", user, "--file", f_msg.name)

    def last_commit_id(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def push(self):
        self._run("push")
