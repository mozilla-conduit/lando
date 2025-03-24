import subprocess
import time

import pytest
import requests
from django.conf import settings
from django.contrib.auth.models import User

from lando.api.legacy.stacks import (
    RevisionStack,
    build_stack_graph,
    request_extended_revision_data,
)
from lando.api.legacy.transplants import build_stack_assessment_state
from lando.main.models import Profile, Repo

# The name of the Phabricator project used to tag revisions requiring data classification.
NEEDS_DATA_CLASSIFICATION_SLUG = "needs-data-classification"


@pytest.fixture
def hg_clone(hg_server, tmpdir):
    clone_dir = tmpdir.join("hg_clone")
    subprocess.run(["hg", "clone", hg_server, clone_dir.strpath], check=True)
    return clone_dir


@pytest.fixture
def hg_test_bundle():
    return settings.BASE_DIR / "api" / "tests" / "data" / "test-repo.bundle"


@pytest.fixture
def hg_server(hg_test_bundle, tmpdir):
    # TODO: Select open port.
    port = "8000"
    hg_url = "http://localhost:" + port

    repo_dir = tmpdir.mkdir("hg_server")
    subprocess.run(["hg", "clone", hg_test_bundle, repo_dir], check=True, cwd="/")

    serve = subprocess.Popen(
        [
            "hg",
            "serve",
            "--config",
            "web.push_ssl=False",
            "--config",
            "web.allow_push=*",
            "-p",
            port,
            "-R",
            repo_dir,
        ]
    )
    if serve.poll() is not None:
        raise Exception("Failed to start the mercurial server.")
    # Wait until the server is running.
    for _i in range(10):
        try:
            requests.get(hg_url)
        except Exception:
            time.sleep(1)
        break

    yield hg_url
    serve.kill()


@pytest.fixture
def conduit_permissions():
    permissions = (
        "scm_level_1",
        "scm_level_2",
        "scm_level_3",
        "scm_conduit",
    )
    all_perms = Profile.get_all_scm_permissions()

    return [all_perms[p] for p in permissions]


@pytest.fixture
def user_plaintext_password() -> str:
    return "test_password"


@pytest.fixture
def user(user_plaintext_password, conduit_permissions):
    user = User.objects.create_user(
        username="test_user",
        password=user_plaintext_password,
        email="testuser@example.org",
    )

    user.profile = Profile(user=user, userinfo={"name": "test user"})

    for permission in conduit_permissions:
        user.user_permissions.add(permission)

    user.save()
    user.profile.save()

    return user


@pytest.fixture
def needs_data_classification_project(phabdouble):
    return phabdouble.project(NEEDS_DATA_CLASSIFICATION_SLUG)


@pytest.fixture
def create_state(
    phabdouble,
    mocked_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    """Create a `StackAssessmentState`."""

    def create_state_handler(revision, landing_assessment=None):
        phab = phabdouble.get_phabricator_client()
        supported_repos = Repo.get_mapping()
        nodes, edges = build_stack_graph(revision)
        stack_data = request_extended_revision_data(phab, list(nodes))
        stack = RevisionStack(set(stack_data.revisions.keys()), edges)
        relman_group_phid = release_management_project["phid"]
        data_policy_review_phid = needs_data_classification_project["phid"]

        return build_stack_assessment_state(
            phab,
            supported_repos,
            stack_data,
            stack,
            relman_group_phid,
            data_policy_review_phid,
            landing_assessment=landing_assessment,
        )

    return create_state_handler
