import logging

from lando.main.config.repos import REPO_CONFIG

logger = logging.getLogger(__name__)


def get_repos_for_env(environment: str):
    from lando.main.models.access_group import AccessGroup
    from lando.main.models.repo import Repo, RepoType

    if environment not in REPO_CONFIG:
        config_keys = ", ".join(REPO_CONFIG.keys())
        logger.warning(
            f"repo config requested for unknown env: {environment}. Available environments: {config_keys}"
        )
        environment = "default"

    repos = REPO_CONFIG.get(environment, {})
    repo_objects = {}

    for repo_name, repo_info in repos.items():
        try:
            existing_repo = Repo.objects.get(name=repo_info.get("name", None))
            repo_objects[repo_name] = existing_repo
        except Repo.DoesNotExist:
            access_group = AccessGroup.objects.get(
                permission=repo_info.get("access_group_permission")
            )
            repo_type = RepoType(repo_info.get("repo_type_enum", None).value)
            repo_data = {
                key: value
                for key, value in repo_info.items()
                if key not in ["access_group_permission", "repo_type_enum"]
            }
            new_repo = Repo(**repo_data, access_group=access_group, repo_type=repo_type)
            new_repo.save()

    return repo_objects
