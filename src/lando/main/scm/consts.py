import enum

SCM_TYPE_GIT = "git"
SCM_TYPE_HG = "hg"

COMMIT_ID_HEX_LENGTH = 40


@enum.unique
class MergeStrategy(str, enum.Enum):
    """Enumeration of acceptable non-default merge strategies.

    This class is a subclass of `str` to enable serialization in Pydantic.
    """

    # Use the current branch's tree, ignoring the target tree.
    OURS = "ours"

    # Use the target branch's tree, ignoring the current tree.
    THEIRS = "theirs"
