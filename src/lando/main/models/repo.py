import logging
import urllib
from pathlib import Path

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

from lando.main.models.base import BaseModel
from lando.main.scm import (
    SCM_IMPLEMENTATIONS,
    AbstractSCM,
    SCMType,
)
from lando.utils.landing_checks import BugReferencesCheck

logger = logging.getLogger(__name__)

# DONTBUILD flag and help text.
DONTBUILD = (
    "DONTBUILD",
    (
        "Should be used only for trivial changes (typo, comment changes,"
        " documentation changes, etc.) where the risk of introducing a"
        " new bug is close to none."
    ),
)

TRY_REPO_NAMES = ("try",)


def validate_path_in_repo_root(value: str):
    path = Path(value)
    if path.parent != Path(settings.REPO_ROOT):
        raise ValidationError(
            f"Path {path} must be a direct child of {settings.REPO_ROOT}."
        )


class RepoError(Exception):
    """An exception that is raised when there is a fatal repository related issue."""

    pass


def get_default_hooks() -> list[str]:
    """Returns a list of all known hook names, suitable as a default value.

    Assuming a normal repository, we enable everything but the BugReferencesCheck, which
    is only relevant for Try-type repos."""
    return [
        hook.name
        for hook in Repo.HooksChoices
        if hook.name != BugReferencesCheck.name()
    ]


class Repo(BaseModel):
    """Represents the configuration of a particular repo."""

    _scm: AbstractSCM | None = None

    class HooksChoices(models.TextChoices):
        """List of landing hooks that can be enabled for a repo."""

        PreventSymlinksCheck = (
            "PreventSymlinksCheck",
            "Check for symlinks introduced in the diff.",
        )
        TryTaskConfigCheck = (
            "TryTaskConfigCheck",
            "Check for `try_task_config.json` introduced in the diff.",
        )
        PreventDotGithubCheck = (
            "PreventDotGithubCheck",
            "Prevent changes to GitHub workflows directory.",
        )
        PreventNSPRNSSCheck = (
            "PreventNSPRNSSCheck",
            "Prevent changes to vendored NSPR directories.",
        )
        PreventSubmodulesCheck = (
            "PreventSubmodulesCheck",
            "Prevent introduction of Git submodules into the repository.",
        )
        CommitMessagesCheck = (
            "CommitMessagesCheck",
            "Check the format of the passed commit message for issues.",
        )
        WPTSyncCheck = (
            "WPTSyncCheck",
            "Check the WPTSync bot is only pushing changes to relevant subset of the tree.",
        )
        BugReferencesCheck = (
            "BugReferencesCheck",
            "Prevent commit messages referencing non-public bugs from try.",
        )

    @property
    def path(self) -> str:
        return str(self.system_path) or self.get_system_path()

    @property
    def is_try(self) -> bool:
        return self.name in TRY_REPO_NAMES

    # TODO: help text for fields below.
    name = models.CharField(max_length=255, unique=True)
    default_branch = models.CharField(max_length=255, default="", blank=True)
    scm_type = models.CharField(
        max_length=3,
        choices=SCMType,
        null=True,
        blank=True,
        default=None,
        help_text="Automatically detected upon saving, will match the type of the remote repo.",
    )
    system_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        validators=[validate_path_in_repo_root],
        help_text="An automatically generated path on the landing worker instance, used to store the contents of the repo.",
    )

    # Legacy fields. These fields were adapted from the legacy implementation of Lando.
    pull_path = models.CharField(
        blank=True,
        help_text="The path that the landing worker should pull from when landing.",
    )
    push_path = models.CharField(
        blank=True,
        help_text="The path that the landing worker should push to when landing.",
    )
    required_permission = models.CharField(
        default="",
        help_text="The permission required to be able to land to this repo. For example, main.scm_conduit.",
    )
    short_name = models.CharField(
        blank=True,
        unique=True,
        help_text="Should match the shortname field on Phabricator for this repo.",
    )
    url = models.CharField()

    approval_required = models.BooleanField(default=False)
    autoformat_enabled = models.BooleanField(default=False)
    commit_flags = ArrayField(
        ArrayField(
            models.CharField(max_length=255, blank=True),
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

    # By default, override any attribute forcing files to be displayed as diffs (rather
    # than binaries).
    attributes_override = models.TextField(
        blank=True,
        default="* !diff\n",
        help_text="SCM-specific attribute override. For git, this is documented in `gitattributes(5)`.",
    )

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
        help_text="If this repo was migrated from a legacy (hg) repo, setting the value here will automatically retarget revisions to this repo.",
    )

    pushlog_disabled = models.BooleanField(
        default=False,
    )

    # Use this field to enable/disable access to this repo via the automation API.
    automation_enabled = models.BooleanField(default=False)

    # Use this field to enable/disable access to this repo via the try API.
    try_enabled = models.BooleanField(default=False)

    # Use this field to enable/disable pre-landing hooks for a repo.
    hooks_enabled = models.BooleanField(default=True)

    hooks = ArrayField(
        models.CharField(max_length=255, blank=False, null=False, choices=HooksChoices),
        blank=True,
        null=True,
        default=get_default_hooks,
    )

    pr_enabled = models.BooleanField(default=False)

    @property
    def is_legacy(self):  # noqa: ANN201
        """Return True if this repo is listed as a legacy source."""
        try:
            return self.new_target is not None
        except self.DoesNotExist:
            return False

    @property
    def is_git(self):  # noqa: ANN201
        return self.scm_type == SCMType.GIT

    @property
    def is_hg(self):  # noqa: ANN201
        return self.scm_type == SCMType.HG

    def __str__(self) -> str:
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
                kwargs = {}
                if self.default_branch:
                    kwargs["default_branch"] = self.default_branch

                self._scm = impl(self.path, **kwargs)
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

        # Strip trailing slash if present in URL.
        self.url = self.url.removesuffix("/")

        # Set or reset SCM type.
        if not self.scm_type:
            self.scm_type = self._find_supporting_scm(self.url)

        # Set pull path if missing.
        if not self.pull_path:
            self.pull_path = self.url

        # Set push path if missing.
        if not self.push_path:
            self.push_path = self.url

        # Set short_name (used in Phabricator) if missing. It should match the legacy
        # tree value, which is equivalent to the repository name.
        if not self.short_name:
            self.short_name = self.tree

        # Set commit flags to an empty list, if not set already.
        if not self.commit_flags:
            self.commit_flags = []

        # Append a ".git" to the URL if this is a GitHub repo and is missing the suffix.
        if self.is_github and not self.url.endswith(".git"):
            self.url += ".git"

        if self.is_git and not self.default_branch:
            self.default_branch = "main"

        super().save(*args, **kwargs)

    @property
    def parsed_url(self) -> urllib.parse.ParseResult:
        """Return the result of parsing the repo URL with urllib.parse.urlparse."""
        return urllib.parse.urlparse(self.url)

    @property
    def is_github(self) -> bool:
        """Return `True` if repo URL is a GitHub URL."""
        return (
            self.is_git
            and self.parsed_url.hostname
            and self.parsed_url.hostname.endswith("github.com")
        )

    @property
    def normalized_url(self) -> str:
        """Return GitHub URL without `.git` suffix, or the original URL.

        For repos hosted on GitHub, remove the `.git` suffix from the URL. This allows the URL
        to be used as a base URL for other paths, e.g. specific commits. For non-GitHub repos,
        return the original URL.
        """
        if self.is_github:
            return self._github_repo_url
        return self.url

    @property
    def _github_repo_url(self) -> str | None:
        if self.is_github:
            return self.url.removesuffix(".git")

    @property
    def _github_repo_org(self) -> str | None:
        if self.is_github:
            return self._github_repo_url.split("/")[-2]

    @property
    def git_repo_name(self) -> str:
        """Provide the bare name of the Git repo."""
        if self.scm_type != SCMType.GIT:
            raise ValueError(f"Not a git repo: {self}")
        return self.url.removesuffix(".git").split("/")[-1]

    def _find_supporting_scm(self, pull_path: str) -> str:
        """Loop through the supported SCM_IMPLEMENTATIONS and return a key representing
        the first SCM claiming to support the given pull_path.
        """
        for scm, impl in SCM_IMPLEMENTATIONS.items():
            if impl.repo_is_supported(pull_path):
                return scm
        raise ValueError(f"Could not determine repo type for {pull_path}")

    @property
    def tree(self):  # noqa: ANN201
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
