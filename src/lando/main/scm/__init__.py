from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.consts import (
    SCM_CHOICES,
    SCM_GIT,
    SCM_HG,
)
from lando.main.scm.exceptions import (
    AutoformattingException,
    NoDiffStartLine,
    PatchApplicationFailure,
    PatchConflict,
    SCMException,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
)
from lando.main.scm.hg import (
    REQUEST_USER_ENV_VAR,
    HgCommandError,
    HgException,
    HgSCM,
    hglib,
)

SCM_IMPLEMENTATIONS = {
    # SCM_GIT: GitSCM,
    SCM_HG: HgSCM,
}

__all__ = [
    # abstract_scm
    "AbstractSCM",
    # consts
    "SCM_HG",
    "SCM_GIT",
    # consts (built up)
    "SCM_CHOICES",
    "SCM_IMPLEMENTATIONS",
    # exceptions
    "SCMException",
    "AutoformattingException",
    "PatchApplicationFailure",
    "NoDiffStartLine",
    "PatchConflict",
    "SCMInternalServerError",
    "SCMLostPushRace",
    "SCMPushTimeoutException",
    "TreeApprovalRequired",
    "TreeClosed",
    # hg
    "hglib",
    "HgException",
    "HgCommandError",
    "HgSCM",
    "REQUEST_USER_ENV_VAR",
]
