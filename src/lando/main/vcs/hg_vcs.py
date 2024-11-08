import logging
from io import StringIO
from pathlib import Path
from typing import ContextManager, Optional

import hglib

from lando.api.legacy.hg import HgRepo
from lando.main.vcs import AbstractVcs

logger = logging.getLogger(__name__)


class HgVcs(AbstractVcs):

    path: str
    hg: HgRepo

    def __init__(self, path: str):
        self.path = path
        self.hg = HgRepo(path)

    def push(
        self, push_path: str, target: Optional[str] = None, force_push: bool = False
    ) -> None:
        self.hg.push(push_path, bookmark=target, force_push=force_push)

    def last_commit_for_path(self, repo_path: str, path: str) -> str:
        return self.hg.run_hg(
            [
                "log",
                "--cwd",
                repo_path,
                "--template",
                "{node}",
                "-l",
                "1",
                path,
            ]
        ).decode()

    def apply_patch(self, patch_buf: StringIO):
        return self.hg.apply_patch(patch_buf)

    def for_push(self, requester_email: str) -> ContextManager:
        return self.hg.for_push(requester_email)

    def for_pull(self) -> ContextManager:
        return self.hg.for_pull()

    # @property
    # def revision_id(self):
    #     """XXX: invalid?"""
    #     return self.hg.revision.revision_id

    def read_checkout_file(self, checkout_file) -> str:
        return self.hg.read_checkout_file(checkout_file)

    def head_ref(self) -> str:
        return self.hg.run_hg(["log", "-r", ".", "-T", "{node}"]).decode("utf-8")

    def changeset_descriptions(self) -> list[str]:
        """Get a description for all the patches to be applied."""
        return (
            self.hg.run_hg(["log", "-r", "stack()", "-T", "{desc|firstline}\n"])
            .decode("utf-8")
            .splitlines()
        )

    def update_repo(self, pull_path: str, target_cset: Optional[str] = None) -> str:
        return self.hg.update_repo(
            pull_path, target_cset.encode() if target_cset else None
        ).decode()

    def format_stack(self, stack_size: int, bug_ids: list[str]) -> Optional[list[str]]:
        return self.hg.format_stack(stack_size, bug_ids)

    def prepare_repo(self, pull_path: str):
        """Either clone or update the repo"""
        if not self.repo_is_initialized:
            Path(self.path).mkdir(parents=True, exist_ok=True)
            logger.info(f"Cloning {self} from pull path.")
            self.hg.clone(pull_path)
        else:
            with self.hg.for_pull():
                logger.info(f"Updating {self} from pull path.")
                self.hg.update_repo(pull_path)

    @property
    def repo_is_initialized(self) -> bool:
        """Returns True if hglib is able to open the repo, otherwise returns False."""
        try:
            self.hg._open()
        except hglib.error.ServerError:
            logger.info(f"{self} appears to be not initialized.")
            return False
        else:
            return True
