# flake8: noqa
from lando.main.scm.abstract_scm import *
from lando.main.scm.consts import *
from lando.main.scm.exceptions import *
from lando.main.scm.git import *
from lando.main.scm.hg import *

# These can only be determined when all the subclasses of the AbstractSCM have been defined.
SCM_CHOICES = {
    klass.scm_type(): klass.scm_name() for klass in AbstractSCM.__subclasses__()
}
SCM_IMPLEMENTATIONS = {
    klass.scm_type(): klass for klass in AbstractSCM.__subclasses__()
}
