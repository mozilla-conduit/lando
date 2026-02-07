import enum

from django.db.models import TextChoices

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


# For cleanliness, this should subclass (str, enum.Enum). However, with a little bit of
# coupling with Django models.TextChoices, which also subclasses (str, enum.Enum), we
# can use this verbatim in Model definitions, too.
class SCMType(TextChoices):
    """Enumeration of acceptable VCS types."""

    GIT = "git", "Git"
    HG = "hg", "Mercurial"
