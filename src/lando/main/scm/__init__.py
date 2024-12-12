from lando.main.scm.abstract_scm import AbstractSCM
from lando.main.scm.consts import (
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
from lando.main.scm.git import GitSCM
from lando.main.scm.hg import (
    REQUEST_USER_ENV_VAR,
    HgCommandError,
    HgException,
    HgSCM,
    hglib,
)

# These can only be determined when all the subclasses of the AbstractSCM have been defined.
SCM_CHOICES = {
    klass.scm_type(): klass.scm_name() for klass in AbstractSCM.__subclasses__()
}
SCM_IMPLEMENTATIONS = {
    klass.scm_type(): klass for klass in AbstractSCM.__subclasses__()
}

__all__ = [
    # abstract_scm
    AbstractSCM,
    # consts
    SCM_HG,
    SCM_GIT,
    # consts (built up)
    SCM_CHOICES,
    SCM_IMPLEMENTATIONS,
    # exceptions
    SCMException,
    AutoformattingException,
    PatchApplicationFailure,
    NoDiffStartLine,
    PatchConflict,
    SCMInternalServerError,
    SCMLostPushRace,
    SCMPushTimeoutException,
    TreeApprovalRequired,
    TreeClosed,
    # git
    GitSCM,
    # hg
    hglib,
    HgException,
    HgCommandError,
    HgSCM,
    REQUEST_USER_ENV_VAR,
]
