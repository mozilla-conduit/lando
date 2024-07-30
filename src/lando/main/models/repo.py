from __future__ import annotations

import json
import urllib
from pathlib import Path
from typing import Union

from django.conf import settings
from django.db import models

from lando.main.config.repos import RepoTypeEnum
from lando.main.interfaces.git_repo_interface import GitRepoInterface
from lando.main.interfaces.hg_repo_interface import HgRepoInterface
from lando.main.models.access_group import AccessGroup
from lando.main.models.base import BaseModel


class RepoType(models.TextChoices):
    GIT = RepoTypeEnum.GIT.value, "Git"
    HG = RepoTypeEnum.HG.value, "Mercurial"


class ListOfTuplesField(models.TextField):
    description = "A list of tuples"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return []
        return json.loads(value)

    def to_python(self, value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return json.loads(value)

    def get_prep_value(self, value):
        if value is None:
            return "[]"
        return json.dumps(value)


class Repo(BaseModel):
    def __str__(self):
        return (
            f"{self.name}_({self.default_branch})"
            if self.repo_type == RepoType.GIT
            else self.name
        )

    repo_type = models.CharField(
        max_length=3, choices=RepoType.choices, default=RepoType.HG
    )

    name = models.CharField(max_length=255, unique=True)
    short_name = models.CharField(max_length=255, default="")
    url = models.CharField(max_length=255)
    push_path = models.CharField(max_length=255)
    pull_path = models.CharField(max_length=255)

    default_branch = models.CharField(max_length=255, default="main")
    system_path = models.FilePathField(
        path=settings.REPO_ROOT,
        max_length=255,
        allow_folders=True,
        blank=True,
        default="",
    )

    access_group = models.ForeignKey(AccessGroup, on_delete=models.CASCADE, null=True)
    push_bookmark = models.CharField(max_length=255, default="")
    approval_required = models.BooleanField(default=False)
    milestone_tracking_flag_template = models.CharField(max_length=255, default="")
    autoformat_enabled = models.BooleanField(default=False)
    commit_flags = ListOfTuplesField(default=[])
    product_details_url = models.CharField(max_length=255, default="")
    is_phabricator_repo = models.BooleanField(default=True)
    force_push = models.BooleanField(default=False)

    is_initialized = models.BooleanField(default=False)

    def __init__(self, *args, **kwargs):
        super(Repo, self).__init__(*args, **kwargs)

        self.repo_type = kwargs.pop("repo_type", RepoType.HG)
        self.system_path = kwargs.get(
            "system_path", str(Path(settings.REPO_ROOT) / self.name)
        )

        self.interface = self._get_repo_interface()

        if not self.push_path or not self.pull_path:
            url = urllib.parse.urlparse(self.url)
            if not self.push_path:
                if RepoType(self.repo_type) == RepoType.HG:
                    self.push_path = f"ssh://{url.netloc}{url.path}"
                else:
                    self.push_path = self.url
            if not self.pull_path:
                self.pull_path = self.url

        if not self.short_name:
            self.short_name = self.name

    @property
    def repo_type_enum(self):
        if self.repo_type == RepoType.GIT:
            return RepoTypeEnum.GIT
        elif self.repo_type == RepoType.HG:
            return RepoTypeEnum.HG
        else:
            raise ValueError(f"Unsupported repo type: {RepoType(self.repo_type)}")

    def _get_repo_interface(self) -> Union[GitRepoInterface, HgRepoInterface]:
        interfaces = {RepoType.GIT: GitRepoInterface, RepoType.HG: HgRepoInterface}
        interface_class = interfaces.get(RepoType(self.repo_type))

        if not interface_class:
            raise ValueError(f"Unsupported repo type: {RepoType(self.repo_type)}")

        return interface_class(self.system_path)

    @property
    def phab_identifier(self) -> str | None:
        """Return a valid Phabricator identifier as a `str`."""
        if not self.is_phabricator_repo:
            return None

        return self.name


class Worker(BaseModel):
    def __str__(self):
        return f"{self.name}"

    name = models.CharField(max_length=255, unique=True)
    is_paused = models.BooleanField(default=False)
    is_stopped = models.BooleanField(default=False)
    ssh_private_key = models.TextField(null=True, blank=True)
    applicable_repos = models.ManyToManyField(Repo)

    throttle_seconds = models.IntegerField(default=10)
    sleep_seconds = models.IntegerField(default=10)

    @property
    def enabled_repos(self) -> list[Repo]:
        return self.applicable_repos.all()
