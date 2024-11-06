import logging
from abc import abstractmethod
from io import StringIO
from pathlib import Path
from typing import ContextManager, Optional

logger = logging.getLogger(__name__)


class AbstractScm:
    """An abstract class defining the interface an SCM needs to expose use by the Repo and LandingWorkers."""

    # The path to the repository.
    path: str

    def __init__(self, path: str):
        self.path = path

    @abstractmethod
    def clone(self, source: str):
        """Clone a repository from a source.
        Args:
            source: The source to clone the repository from.
        Returns:
            None
        """

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

    @abstractmethod
    def clean_repo(self, *, strip_non_public_commits: bool = True):
        """Clean the local working copy from all extraneous files.

        If `strip_non_public_commits` is set, also rewind any commit not present on the
        origin."""

    @abstractmethod
    def last_commit_for_path(self, path: str) -> str:
        """Find last commit to touch a path.

        Args:
            path (str): The specific path within the repository.

        Returns:
            str: The commit id
        """

    @abstractmethod
    def apply_patch(self, patch_buf: StringIO):
        """Apply the given patch to the current repository

        Args:
            patch_buf (StringIO): The patch to apply

        Returns:
            None
        """

    @abstractmethod
    def for_pull(self) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pulling."""

    @abstractmethod
    def for_push(self, requester_email: str) -> ContextManager:
        """Context manager to prepare the repo with the correct environment variables set for pushing.

        Args:
            requester_email (str)
        """

    def read_checkout_file(self, checkout_file: str) -> str:
        """Return the contents of the file at `path` in the checkout as a `str`."""
        checkout_file_path = Path(self.path) / checkout_file

        if not checkout_file_path.exists():
            raise ValueError(f"File at {checkout_file_path} does not exist.")

        with checkout_file_path.open() as f:
            return f.read()

    @abstractmethod
    def head_ref(self) -> str:
        """Get the current revision_id."""

    @abstractmethod
    def changeset_descriptions(self) -> list[str]:
        """Retrieve the descriptions of commits in the repository.

        Returns:
            list[str]: A list of first lines of changeset descriptions.
        """

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

    @abstractmethod
    def prepare_repo(self, pull_path: str):
        """Either clone or update the repo."""
        if not self.repo_is_initialized:
            Path(self.path).mkdir(parents=True, exist_ok=True)
            logger.info(f"Cloning {self} from pull path.")
            self.clone(pull_path)
        else:
            with self.for_pull():
                logger.info(f"Updating {self} from pull path.")
                self.update_repo(pull_path)

    @property
    @abstractmethod
    def repo_is_initialized(self) -> bool:
        """Determine whether the target repository is initialised."""

    @classmethod
    @abstractmethod
    def repo_is_supported(cls, path: str) -> bool:
        """Determine wether the target repository is supported by this concrete implementation."""
