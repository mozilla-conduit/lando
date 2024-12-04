import logging
from abc import abstractmethod
from pathlib import Path
from typing import ContextManager, Optional

logger = logging.getLogger(__name__)


class AbstractSCM:
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
    def apply_patch(
        self, diff: str, commit_description: str, commit_author: str, commit_date: str
    ):
        """Apply the given patch to the current repository.

        Args:
            diff (str): A unified diff representation of the patch.
            commit_description (str): The commit message.
            commit_author (str): The commit author.
            commit_date (str): The commit date.

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

    @abstractmethod
    def format_stack_amend(self) -> Optional[list[str]]:
        """Amend the top commit in the patch stack with changes from formatting.

        Returns a list containing a single string representing the ID of the amended commit.
        """

    @abstractmethod
    def format_stack_tip(self, commit_message: str) -> Optional[list[str]]:
        """Add an autoformat commit to the top of the patch stack.

        Returns a list containing a single string representing the ID of the newly created commit.
        """
