import pytest
from django.contrib import admin

from lando.headless_api.admin import AutomationJobAdmin
from lando.headless_api.models.automation_job import AutomationJob
from lando.main.admin import (
    HackbotResolutionAdmin,
    LandingJobAdmin,
    RepoAdmin,
    UpliftJobAdmin,
)
from lando.main.models.landing_job import LandingJob
from lando.main.models.repo import SCMType
from lando.main.models.uplift import HackbotResolution, UpliftJob


@pytest.mark.parametrize(
    "admin_class,job_class,expected_path",
    (
        (LandingJobAdmin, LandingJob, "/landings/1/"),
        (AutomationJobAdmin, AutomationJob, "/api/jobs/1/"),
        (UpliftJobAdmin, UpliftJob, "/uplift/jobs/1/"),
    ),
)
def test_JobAdmin__view_on_site(admin_class: type, job_class: type, expected_path: str):
    job_admin = admin_class(job_class, admin.site)

    assert job_admin.view_on_site(job_class(id=1)) == expected_path, (
        f"`view_on_site` should point at the details page of the {job_class.type} job."
    )


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


def test_HackbotResolutionAdmin_is_read_only(rf):
    request = rf.get("/admin/")
    resolution_admin = admin.site.get_model_admin(HackbotResolution)

    assert isinstance(resolution_admin, HackbotResolutionAdmin), (
        "`HackbotResolution` should be registered with `HackbotResolutionAdmin`."
    )
    assert not resolution_admin.has_add_permission(request), (
        "Resolutions should not be addable from the admin."
    )
    assert not resolution_admin.has_change_permission(request), (
        "Resolutions should not be editable from the admin."
    )
    assert not resolution_admin.has_delete_permission(request), (
        "Resolutions should not be deletable from the admin."
    )
    assert {"patch", "conflict_diff", "resolution_diff"}.isdisjoint(
        resolution_admin.list_display
    ), "The large patch and diffs should only be shown on the detail page."
