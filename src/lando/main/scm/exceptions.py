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

    pass


class NoDiffStartLine(PatchApplicationFailure):
    """Exception when patch is missing a Diff Start Line header."""

    pass


class PatchConflict(PatchApplicationFailure):
    """Exception when patch fails to apply due to a conflict."""

    pass


class ScmInternalServerError(ScmException):
    pass


class ScmLostPushRace(ScmException):
    pass


class ScmPushTimeoutException(ScmException):
    pass


class TreeApprovalRequired(ScmException):
    pass


class TreeClosed(ScmException):
    pass
