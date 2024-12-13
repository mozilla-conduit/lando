from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.consts import (
    SCM_TYPE_CHOICES,
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
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
    # SCM_TYPE_GIT: GitSCM,
    SCM_TYPE_HG: HgSCM,
}

__all__ = [
    # abstract_scm
    "AbstractSCM",
    # consts
    "SCM_TYPE_HG",
    "SCM_TYPE_GIT",
    # consts (built up)
    "SCM_TYPE_CHOICES",
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
