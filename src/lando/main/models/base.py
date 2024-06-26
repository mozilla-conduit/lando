from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from contextlib import ContextDecorator
from pathlib import Path

from django.conf import settings
from django.db import connection, models, transaction

from lando.utils import GitPatchHelper

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


class LockTableContextManager(ContextDecorator):
    """Decorator to lock table for current model."""

    def __init__(self, model, lock="SHARE ROW EXCLUSIVE"):
        self.lock = lock
        self.model = model

        if lock not in ("SHARE ROW EXCLUSIVE",):
            raise ValueError(f"{lock} not valid.")

    def __enter__(self):
        cursor = connection.cursor()
        with transaction.atomic():
            cursor.execute(
                f"LOCK TABLE {self.model._meta.db_table} IN {self.lock} MODE"
            )

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @classmethod
    @property
    def lock_table(cls):
        return LockTableContextManager(cls)

    @classmethod
    def one_or_none(cls, *args, **kwargs):
        try:
            result = cls.objects.get(*args, **kwargs)
        except cls.DoesNotExist:
            return None
        return result


class Repo(BaseModel):
    def __str__(self):
        return f"{self.name} ({self.default_branch})"

    name = models.CharField(max_length=255, unique=True)
    default_branch = models.CharField(max_length=255, default="main")
    url = models.CharField(max_length=255)
    push_path = models.CharField(max_length=255)
    pull_path = models.CharField(max_length=255)
    is_initialized = models.BooleanField(default=False)

    system_path = models.FilePathField(
        path=settings.REPO_ROOT,
        max_length=255,
        allow_folders=True,
        blank=True,
        default="",
    )

    def _run(self, *args, cwd=None):
        cwd = cwd or self.system_path
        command = ["git"] + list(args)
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        return result

    def initialize(self):
        self.refresh_from_db()

        if self.is_initialized:
            raise

        repo_root = Path(settings.REPO_ROOT)
        repo_root.mkdir(parents=True, exist_ok=True)
        self.system_path = repo_root / self.name

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
        self._run(
            "push", self.push_path.replace("[TOKEN]", settings.GITHUB_ACCESS_TOKEN)
        )


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

    @property
    def enabled_repo_names(self) -> list[str]:
        return self.enabled_repos.values_list("name", flat=True)
