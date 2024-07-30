# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from lando.main.util import get_repos_for_env

logger = logging.getLogger(__name__)


class RepoError(Exception):
    pass


class InvalidPathError(RepoError):
    pass


class Command(BaseCommand):
    help = (
        "Synchronize all repositories specified in the configuration for "
        "this Lando instance by performing 'clone' and 'pull' operations."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        repo_clone_root = settings.REPO_ROOT

        try:
            if not repo_clone_root:
                raise RepoError("settings.REPO_ROOT is not defined.")

            self.repo_clone_root_path = Path(settings.REPO_ROOT)
            if (
                not self.repo_clone_root_path.exists()
                or not self.repo_clone_root_path.is_dir()
            ):
                raise InvalidPathError(
                    f"REPO_ROOT ({self.repo_clone_root_path}) is not a valid "
                    f"path to an existing directory for holding repository clones."
                )

            self.repos = get_repos_for_env(settings.ENVIRONMENT)

        except Exception as e:
            logger.error(
                "An error occurred during initialization: %s", e, exc_info=True
            )
            raise e

    def handle(self, *args, **kwargs):
        for name, repo in self.repos.items():
            if Path(repo.system_path).exists() and repo.is_initialized:
                logger.info("Repo exists, pulling.", extra={"repo": name})
                with repo.interface.pull_context():
                    repo.interface.update_repo(repo.pull_path)
            else:
                if repo.is_initialized:
                    raise RepoError(
                        "The repository is initialized in the database, but does not exist on disk."
                    )
                logger.info("Cloning repo.", extra={"repo": name})
                repo.interface.clone(repo.pull_path)
                repo.is_initialized = True
                repo.save()

            # Ensure packages required for automated code formatting are installed.
            if repo.autoformat_enabled:
                repo.interface.run_mach_bootstrap()

            logger.info("Repo ready.", extra={"repo": name})
