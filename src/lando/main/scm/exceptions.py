from typing import Optional


class ScmException(Exception):
    """A base exception class for errors coming from interactions with an SCM."""

    out: str
    err: str
    msg: str

    def __init__(self, msg: str, out: str, err: str = ""):
        self.out = out
        self.err = err
        super().__init__(msg)


class AutoformattingException(Exception):
    def __init__(self, *args: object, details: Optional[str] = None) -> None:
        super().__init__(
            *args,
        )

        self._details = details

    def details(self) -> str:
        """Return error details for display."""
        return self._details if self._details else str(self)


class PatchApplicationFailure(Exception):
    """Exception when there is a failure applying a patch."""


class NoDiffStartLine(PatchApplicationFailure):
    """Exception when patch is missing a Diff Start Line header."""


class PatchConflict(PatchApplicationFailure):
    """Exception when patch fails to apply due to a conflict."""


class ScmInternalServerError(ScmException):
    """Exception when pulling changes from the upstream repo fails."""


class ScmLostPushRace(ScmException):
    """Exception when pushing failed due to another push happening."""


class ScmPushTimeoutException(ScmException):
    """Exception when pushing failed due to a timeout on the repo."""


class TreeApprovalRequired(ScmException):
    """Exception when pushing failed due to approval being required."""


class TreeClosed(ScmException):
    """Exception when pushing failed due to a closed tree."""
