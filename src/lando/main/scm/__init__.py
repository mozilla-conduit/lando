from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.commit import CommitData
from lando.main.scm.consts import (
    SCM_TYPE_GIT,
    SCM_TYPE_HG,
    MergeStrategy,
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
from lando.main.scm.git import GitSCM
from lando.main.scm.hg import (
    REQUEST_USER_ENV_VAR,
    HgCommandError,
    HgException,
    HgSCM,
)

# These can only be determined when all the subclasses of the AbstractSCM have been defined.
SCM_TYPE_CHOICES = {
    klass.scm_type(): klass.scm_name() for klass in AbstractSCM.__subclasses__()
}
SCM_IMPLEMENTATIONS = {
    klass.scm_type(): klass for klass in AbstractSCM.__subclasses__()
}

__all__ = [
    # abstract_scm
    "AbstractSCM",
    # commit
    CommitData,
    # consts
    "SCM_TYPE_HG",
    "SCM_TYPE_GIT",
    "MergeStrategy",
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
    # git
    "GitSCM",
    # hg
    "HgException",
    "HgCommandError",
    "HgSCM",
    "REQUEST_USER_ENV_VAR",
]
