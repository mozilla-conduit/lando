import os
from unittest import mock

import pytest

from lando.api.legacy.workers.landing_worker import LandingWorker
from lando.main.scm import SCM_TYPE_GIT, SCM_TYPE_HG


@pytest.mark.parametrize(
    "scm_type",
    [
        SCM_TYPE_HG,
        SCM_TYPE_GIT,
    ],
)
@mock.patch.dict(os.environ, {LandingWorker.SSH_PRIVATE_KEY_ENV_KEY: ""})
@pytest.mark.django_db
def test_Worker__no_SSH_PRIVATE_KEY(caplog, landing_worker_instance, scm_type):
    # The worker will read the environment and try to handle the SSH_PRIVATE_KEY if
    # present.
    w = LandingWorker(landing_worker_instance(scm=scm_type), with_ssh=True)

    # Let the runner terminate immediately after setup.
    w.start(max_loops=-1)

    # It should complain, but continue.
    assert LandingWorker.SSH_PRIVATE_KEY_ENV_KEY in caplog.text
