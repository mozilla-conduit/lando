import uuid

import pytest
from django.contrib import admin
from django.urls import reverse

from lando.headless_api.admin import AutomationJobAdmin
from lando.headless_api.models.automation_job import AutomationJob
from lando.main.admin import (
    HackbotResolutionAdmin,
    LandingJobAdmin,
    RepoAdmin,
    UpliftJobAdmin,
    UsedHackbotChoices,
    UsedHackbotFilter,
)
from lando.main.models import JobStatus, Revision
from lando.main.models.landing_job import LandingJob
from lando.main.models.repo import SCMType
from lando.main.models.uplift import (
    HackbotResolution,
    UpliftAssessment,
    UpliftJob,
    UpliftSubmission,
)


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


@pytest.fixture
def make_uplift_job(repo_mc, user):
    """Return a factory for uplift jobs on one repo, with or without a resolution."""
    repo = repo_mc(SCMType.GIT, name="firefox-beta")
    revision = Revision.objects.create(revision_id=1)
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="Medium",
        covered_by_testing="yes",
        fix_verified_in_nightly="yes",
        needs_manual_qe_testing="no",
        risk_associated_with_patch="low",
        risk_level_explanation="low risk",
        string_changes="none",
        is_android_affected="no",
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user, assessment=assessment, requested_revision_ids=[1]
    )

    def make(resolution_count: int) -> UpliftJob:
        job = UpliftJob.objects.create(
            status=JobStatus.LANDED,
            requester_email=user.email,
            target_repo=repo,
            submission=submission,
        )
        for _ in range(resolution_count):
            HackbotResolution.objects.create(
                job=job,
                conflict_revision=revision,
                base_commit="a" * 40,
                run_id=uuid.uuid4(),
            )
        return job

    return make


@pytest.mark.django_db
def test_UpliftJobAdmin_flags_and_filters_jobs_that_used_hackbot(rf, make_uplift_job):
    hackbot_job = make_uplift_job(resolution_count=2)
    clean_job = make_uplift_job(resolution_count=0)
    job_admin = admin.site.get_model_admin(UpliftJob)
    request = rf.get("/admin/")
    jobs = {job.id: job for job in job_admin.get_queryset(request)}

    assert job_admin.used_hackbot(jobs[hackbot_job.id]) is True, (
        "A job with Hackbot resolutions should be flagged as having used Hackbot."
    )
    assert job_admin.used_hackbot(jobs[clean_job.id]) is False, (
        "A job without Hackbot resolutions should not be flagged."
    )
    assert "used_hackbot" in job_admin.list_display, (
        "The Hackbot flag should be shown in the uplift job list."
    )

    for value, expected in (
        (UsedHackbotChoices.YES, hackbot_job),
        (UsedHackbotChoices.NO, clean_job),
    ):
        job_filter = UsedHackbotFilter(
            request, {"used_hackbot": [value]}, UpliftJob, job_admin
        )
        filtered = job_filter.queryset(request, job_admin.get_queryset(request))
        assert list(filtered) == [expected], (
            f"Filtering on `used_hackbot={value}` should return only job {expected.id}."
        )


@pytest.mark.django_db
def test_UpliftJobAdmin_links_to_hackbot_resolutions(make_uplift_job):
    hackbot_job = make_uplift_job(resolution_count=2)
    clean_job = make_uplift_job(resolution_count=0)
    job_admin = admin.site.get_model_admin(UpliftJob)

    links = job_admin.hackbot_resolution_links(hackbot_job)

    for resolution in hackbot_job.hackbot_resolutions.all():
        url = reverse("admin:main_hackbotresolution_change", args=(resolution.pk,))
        assert f'href="{url}"' in links, (
            f"The job page should link to resolution {resolution.pk} in the admin."
        )
    assert job_admin.hackbot_resolution_links(clean_job) == "-", (
        "A job without Hackbot resolutions should show a placeholder."
    )
    assert "hackbot_resolution_links" in job_admin.fields, (
        "The resolution links should be shown on the uplift job page."
    )
