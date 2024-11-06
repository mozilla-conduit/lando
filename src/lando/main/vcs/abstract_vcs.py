import logging
from abc import abstractmethod
from io import StringIO
from typing import ContextManager, Optional

logger = logging.getLogger(__name__)


class AbstractVcs:
    """An abstract class defining the interface a VCS needs to expose use by the Repo and LandingWorkers."""

    @abstractmethod
    def push(
        self, push_path: str, target: Optional[str] = None, force_push: bool = False
    ):
        """Push local code to the remote repository.

        Parameters:
            push_path (str): The path to the repository where changes will be pushed.
            target (Optional[str]): The target branch or reference to push to. Defaults to None.
            force_push (bool): If True, force the push even if it results in a non-fast-forward update. Defaults to False.

        Returns:
            None
        """

        pass

    @abstractmethod
    def last_commit_for_path(self, repo_path: str, path: str) -> bytes:
        """
        Find last commit to touch a path.

        Args:
            repo_path (str): The path to the repository.
            path (str): The specific path within the repository.

        Returns:
            bytes: The commit id
        """
        pass

    @abstractmethod
    def apply_patch(self, patch_buf: StringIO):
        """Apply the given patch to the current repository

        Args:
            patch_buf (StringIO): The patch to apply

        Returns:
            None
        """
        pass

    @abstractmethod
    def for_pull(self) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pulling."""
        pass

    @abstractmethod
    def for_push(self, requester_email: str) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pushing.

        Args:
            requester_email (str)
        """
        pass

    # @property
    # @abstractmethod
    # def revision_id(self):
    #     """Get the current revision_id. XXX: likely unused and broken"""
    #     pass

    @abstractmethod
    def read_checkout_file(self, checkout_file: str) -> str:
        """Return the contents of the file at `path` in the checkout as an `str`."""
        pass

    @abstractmethod
    def head_ref(self) -> str:
        """Get the current revision_id"""
        pass

    @abstractmethod
    def changeset_descriptions(self) -> list[str]:
        """Retrieve the descriptions of commits in the repository.

        Returns:
            list[str]: A list of first lines of changeset descriptions.
        """
        pass

    @abstractmethod
    def update_repo(self, pull_path: str, target_cset: Optional[str] = None) -> str:
        """Update the repository to the specified changeset.

        This method uses the Mercurial command to update the repository
        located at the given pull path to the specified target changeset.

        Args:
            pull_path (str): The path to pull from.
            target_cset (str): The target changeset to update the repository to.

        Returns:
            str: The target changeset
        """
        pass

    @abstractmethod
    def format_stack(self, stack_size: int, bug_ids: list[str]) -> Optional[list[str]]:
        """Format the stack of changesets with the given size and bug IDs.

        This method uses the Mercurial command to format the stack of changesets
        based on the specified stack size and list of bug IDs.

        Args:
            stack_size (int): The size of the stack to format.
            bug_ids (list[str]): A list of bug IDs to include in the stack.

        Returns:
            list[str]: The result of the Mercurial format stack command, or None in case of error
        """
        pass

    @abstractmethod
    def prepare_repo(self, pull_path: str):
        """Clone or update the repository

        Args:
            pull_path (str): The path to clone from.
        """
        pass

    @property
    @abstractmethod
    def repo_is_initialized(self) -> bool:
        """Determine whether the target repository is initialised"""
        pass
