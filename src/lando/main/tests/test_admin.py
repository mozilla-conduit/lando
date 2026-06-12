import pytest

from lando.main.admin import RepoAdmin
from lando.main.models.repo import SCMType


@pytest.mark.xfail
@pytest.mark.django_db(transaction=True)
def test_RepoAdmin__form__clear_gh_hmac_secret(repo_mc):
    """Test that passing "-" clears the gh_hmac_secret."""
    repo = repo_mc(SCMType.GIT, name="test")
    data = {"gh_hmac_secret": "-"}
    repo.set_gh_hmac_secret("test")
    assert repo.gh_hmac_secret == "test"
    test_form = RepoAdmin.form(data, instance=repo)

    # This currently causes a test failure. See bug 2046544.
    assert test_form.is_valid()
    test_form.save()
    assert repo.gh_hmac_secret == ""
