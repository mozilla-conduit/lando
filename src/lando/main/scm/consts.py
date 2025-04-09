import enum

SCM_TYPE_GIT = "git"
SCM_TYPE_HG = "hg"


@enum.unique
class MergeStrategy(str, enum.Enum):
    """Enumeration of acceptable non-default merge strategies.

    This class is a subclass of `str` to enable serialization in Pydantic.
    """

    Ours = "ours"
    Theirs = "theirs"
