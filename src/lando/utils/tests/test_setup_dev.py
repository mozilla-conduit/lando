import pytest
from django.test import override_settings

from lando.environments import Environment
from lando.main.models import Repo
from lando.main.scm import SCMType
from lando.treestatus.models import Log, Tree, TreeCategory, TreeStatus
from lando.utils.management.commands.setup_dev import ADMIN_EMAIL, Command


@pytest.fixture
def new_repo():
    """Create a `Repo` without probing the URL for a supporting SCM."""

    def _new_repo(name: str, is_try: bool = False) -> Repo:
        return Repo.objects.create(
            name=name,
            url=f"http://hg.test/{name}",
            scm_type=SCMType.HG,
            is_try=is_try,
        )

    return _new_repo


@pytest.mark.django_db
@override_settings(ENVIRONMENT=Environment.local)
def test_setup_treestatus_trees_creates_a_tree_per_repo(new_repo):
    new_repo("first-repo")
    new_repo("try", is_try=True)

    Command().setup_treestatus_trees()

    assert Tree.objects.count() == 2, "Every repo should be given a tree."

    first_repo = Tree.objects.get(tree="first-repo")
    assert first_repo.status == TreeStatus.OPEN, (
        "Seeded trees should be open so landing is not blocked by default."
    )
    assert first_repo.category == TreeCategory.DEVELOPMENT, (
        "A non-try repo should be categorized as a development tree."
    )
    assert Tree.objects.get(tree="try").category == TreeCategory.TRY, (
        "A try repo should be categorized as a try tree."
    )
    logs = Log.objects.filter(tree="first-repo")
    assert logs.count() == 1, "Seeding a tree should record an initial log entry."
    assert logs.get().changed_by == ADMIN_EMAIL, (
        "The initial log entry should be attributed to the local admin user."
    )
