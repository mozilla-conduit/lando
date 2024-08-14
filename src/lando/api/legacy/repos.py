from __future__ import annotations

import logging
import pathlib
from typing import Optional

from django.conf import settings

from lando.api.legacy.systems import Subsystem
from lando.main.models import Repo
from lando.main.models.profile import SCM_PERMISSIONS

logger = logging.getLogger(__name__)

SCM_PERMISSIONS_MAP = {value: f"main.{key}" for key, value in SCM_PERMISSIONS}

SCM_ALLOW_DIRECT_PUSH = SCM_PERMISSIONS_MAP["SCM_ALLOW_DIRECT_PUSH"]
SCM_CONDUIT = SCM_PERMISSIONS_MAP["SCM_CONDUIT"]
SCM_FIREFOXCI = SCM_PERMISSIONS_MAP["SCM_FIREFOXCI"]
SCM_L10N_INFRA = SCM_PERMISSIONS_MAP["SCM_L10N_INFRA"]
SCM_LEVEL_1 = SCM_PERMISSIONS_MAP["SCM_LEVEL_1"]
SCM_LEVEL_2 = SCM_PERMISSIONS_MAP["SCM_LEVEL_2"]
SCM_LEVEL_3 = SCM_PERMISSIONS_MAP["SCM_LEVEL_3"]
SCM_NSS = SCM_PERMISSIONS_MAP["SCM_NSS"]
SCM_VERSIONCONTROL = SCM_PERMISSIONS_MAP["SCM_VERSIONCONTROL"]

# DONTBUILD flag and help text.
DONTBUILD = (
    "DONTBUILD",
    (
        "Should be used only for trivial changes (typo, comment changes,"
        " documentation changes, etc.) where the risk of introducing a"
        " new bug is close to none."
    ),
)


def get_repo_mapping() -> dict[str, Repo]:
    all_repos = Repo.objects.all()
    return {repo.tree: repo for repo in all_repos}


class RepoCloneSubsystem(Subsystem):
    name = "repo_clone"

    def ready(self) -> Optional[bool | str]:
        clones_path = settings.REPO_CLONES_PATH
        repo_names = settings.REPOS_TO_LAND

        if not clones_path and not repo_names:
            return None

        clones_path = pathlib.Path(settings.REPO_CLONES_PATH)
        if not clones_path.exists() or not clones_path.is_dir():
            return (
                "REPO_CLONES_PATH ({}) is not a valid path to an existing "
                "directory for holding repository clones.".format(clones_path)
            )

        repo_names = set(filter(None, (name.strip() for name in repo_names.split(","))))
        if not repo_names:
            return (
                "REPOS_TO_LAND does not contain a valid comma seperated list "
                "of repository names."
            )

        repos = get_repo_mapping()
        if not all(name in repos for name in repo_names):
            return "REPOS_TO_LAND contains unsupported repository names."

        self.repos = {name: repos[name] for name in repo_names}
        self.repo_paths = {}

        from lando.api.legacy.hg import HgRepo

        for name, repo in self.repos.items():
            path = clones_path.joinpath(name)
            hgrepo = HgRepo(str(path))

            if path.exists():
                logger.info("Repo exists, pulling.", extra={"repo": name})
                with hgrepo.for_pull():
                    hgrepo.update_repo(repo.pull_path)
            else:
                logger.info("Cloning repo.", extra={"repo": name})
                hgrepo.clone(repo.pull_path)

            # Ensure packages required for automated code formatting are installed.
            if repo.autoformat_enabled:
                hgrepo.run_mach_bootstrap()

            logger.info("Repo ready.", extra={"repo": name})
            self.repo_paths[name] = path

        return True


repo_clone_subsystem = RepoCloneSubsystem()
