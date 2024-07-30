from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from lando.main.config.repos import RepoTypeEnum
from lando.main.models.repo import Repo, Worker
from lando.main.util import get_repos_for_env

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ensure the repos for the environment exist in the database."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.git_worker = self._get_or_create_worker("git-landing-worker")
        self.hg_worker = self._get_or_create_worker("hg-landing-worker")

    def handle(self, *args, **options):
        repos = get_repos_for_env(settings.ENVIRONMENT)

        for _repo_name, repo_object in repos.items():
            self._add_repo_to_worker(repo_object)

    @staticmethod
    def _get_or_create_worker(worker_name: str):
        worker, created = Worker.objects.get_or_create(name=worker_name)
        return worker

    def _add_repo_to_worker(self, repo: Repo):
        workers = {
            RepoTypeEnum.GIT: self.git_worker,
            RepoTypeEnum.HG: self.hg_worker,
        }

        worker = workers.get(repo.repo_type_enum)

        if not worker:
            raise ValueError(f"Unsupported repo type: {repo.repo_type_enum}")

        worker.applicable_repos.add(repo)
        worker.save()
