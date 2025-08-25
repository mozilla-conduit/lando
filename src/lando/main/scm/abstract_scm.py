import logging
import random
import string
from abc import abstractmethod
from pathlib import Path
from typing import Any, ContextManager, Optional

from lando.main.scm.commit import CommitData
from lando.main.scm.consts import MergeStrategy
from lando.main.scm.helpers import PatchHelper

logger = logging.getLogger(__name__)


class AbstractSCM:
    """An abstract class defining the interface an SCM needs to expose use by the Repo and LandingWorkers."""

    # The path to the repository.
    path: str

    def __init__(self, path: str, **kwargs):
        self.path = path

    def __str__(self) -> str:
        return f"{self.scm_name()} repo at {self.path}"

    @classmethod
    @abstractmethod
    def scm_type(cls) -> str:
        """Return a string identifying the supported SCM (e.g., `hg`; see the `SCM_*`
        constants)."""

    @classmethod
    @abstractmethod
    def scm_name(cls) -> str:
        """Return a _human-friendly_ string identifying the supported SCM (e.g.,
        `Mercurial`)."""

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
        self,
        push_path: str,
        push_target: Optional[str] = None,
        force_push: bool = False,
        tags: list[str] | None = None,
    ):
        """Push local code to the remote repository.

        Parameters:
            push_path (str): The path to the repository where changes will be pushed. It
            will remain unspecified if None or empty string.
            target (Optional[str]): The target branch or reference to push to. Defaults to None.
            force_push (bool): If True, force the push even if it results in a non-fast-forward update. Defaults to False.
            tags (Optional[list[str]]): List of tags to push, if applicable.

        Returns:
            None
        """

    @abstractmethod
    def clean_repo(
        self,
        *,
        strip_non_public_commits: bool = True,
        attributes_override: str | None = None,
    ):
        """Clean the local working copy from all extraneous files.

        If `strip_non_public_commits` is set, also rewind any commit not present on the
        origin.

        `attributes_override` is SCM-dependent.

        """

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
    def apply_patch_bytes(self, patch_bytes: bytes):
        """Apply the given bytes representing a patch to the current repository.

        Args:
            patch_bytes (bytes): A patch in the concrete SCM's standard format.

        Returns:
            None
        """

    @abstractmethod
    def get_patch(self, revision_id: str) -> str | None:
        """Return a complete patch for the given revision, in the git extended diff format.

        Args:
            revision_id (str): The ID of the revision / commit to return a patch for.

        Returns:
            str: The patch for the selected commit, or None if not applicable (e.g. for a
            merge commit).

        """

    @abstractmethod
    def get_patch_helper(self, revision_id: str) -> PatchHelper | None:
        """Return a PatchHelper containing the patch for the given revision.

        Args:
            revision_id (str): The ID of the revision / commit to return a patch for.

        Returns:
            PatchHelper: a PatchHelper containing the patch for the specified revision.

        """

    @abstractmethod
    def process_merge_conflict(
        self, pull_path: str, revision_id: int, error_message: str
    ) -> dict[str, Any]:
        """Process merge conflict information captured in a PatchConflict, and return a
        parsed structure.

        The structure is a nested dict as follows:

            revision_id: revision_id
            failed paths: list[dict]
                path: str
                url: str
                changeset_id: str
            rejects_paths: dict[str, dict]
                <str>: dict[str, str] (conflicted file path)
                    path: str (reject file path)
                    content: str
        """

    @abstractmethod
    def describe_commit(self, revision_id: str) -> CommitData:
        """Return Commit metadata."""

    @abstractmethod
    def describe_local_changes(self, base_cset: str = "") -> list[CommitData]:
        """Return a list of the Commits only present on this branch.

        Commits are sorted in ascending topological order.

        If `base_cset` is passed, use it as the public base to find changes against.
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
    def update_repo(
        self,
        pull_path: str,
        target_cset: Optional[str] = None,
        attributes_override: str | None = None,
    ) -> str:
        """Update the repository to the specified changeset.

        This method uses the Mercurial command to update the repository
        located at the given pull path to the specified target changeset.

        The target changeset will be used as the base onto which the next commits will
        be applied.

        Args:
            pull_path (str): The path to pull from.
            target_cset (str): The target changeset to update the repository to.
            attributes_override: Arbitrary attributes to override (SCM-dependent).

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

    @staticmethod
    def _separator() -> str:
        """Generate a long random string usable as a separator.

        This is useful when parsing semi-structured multiline text output."""
        return "".join(random.choices(string.ascii_uppercase, k=16))

    @abstractmethod
    def merge_onto(
        self, commit_message: str, target: str, strategy: Optional[MergeStrategy]
    ) -> str:
        """Create a merge commit on the specified repo.

        Use the specified `MergeStrategy` if passed. Otherwise, perform
        a normal merge and fail if there are merge conflicts.

        Return the SHA of the newly created merge commit.
        """

    @abstractmethod
    def tag(self, name: str, target: str | None):
        """Create a new tag called `name` on the `target` commit.

        If `target` is `None`, use the currently checked out commit.
        """
