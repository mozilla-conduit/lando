"""Render tests for the uplift pages outside the revision view."""

import pytest
from django.urls import reverse

from lando.conftest import UPLIFT_ASSESSMENT_ANSWERS
from lando.main.models import JobStatus
from lando.main.models.uplift import (
    UpliftAssessment,
    UpliftJob,
    UpliftSubmission,
)
from lando.main.scm import SCMType

BUG_ID = 777777


@pytest.mark.django_db
def test_uplift_job_page_renders(authenticated_client, user, repo_mc):
    """The job detail page the assessment cards link to still renders."""
    repo = repo_mc(scm_type=SCMType.GIT, name="firefox-beta", approval_required=True)

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=BUG_ID, **UPLIFT_ASSESSMENT_ANSWERS
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user, assessment=assessment, requested_revision_ids=[100]
    )
    job = UpliftJob.objects.create(
        submission=submission,
        requester_email=user.email,
        status=JobStatus.SUBMITTED,
        target_repo=repo,
    )

    response = authenticated_client.get(reverse("uplift-jobs-page", args=[job.id]))

    assert response.status_code == 200, "The uplift job page should render."
    assert response.context_data["job"] == job, "The page should show the job."


@pytest.mark.django_db
def test_uplift_job_page_renders_a_failed_job(authenticated_client, user, repo_mc):
    """A failed job renders its error breakdown rather than erroring itself."""
    repo = repo_mc(scm_type=SCMType.GIT, name="firefox-beta", approval_required=True)

    assessment = UpliftAssessment.objects.create(
        user=user, bug_id=BUG_ID, **UPLIFT_ASSESSMENT_ANSWERS
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user, assessment=assessment, requested_revision_ids=[100]
    )
    job = UpliftJob.objects.create(
        submission=submission,
        requester_email=user.email,
        status=JobStatus.FAILED,
        target_repo=repo,
        error="Patch did not apply cleanly.",
        error_breakdown={
            "failed_paths": [{"path": "browser/base/foo.js", "url": "http://x/foo"}],
            "rejects_paths": [
                {"path": "browser/base/foo.js", "content": "@@ -1 +1 @@"}
            ],
        },
    )

    response = authenticated_client.get(reverse("uplift-jobs-page", args=[job.id]))

    assert response.status_code == 200, "A failed uplift job page should render."
    assert "Patch did not apply cleanly." in response.content.decode(), (
        "The failure reason should be shown on the job page."
    )


@pytest.mark.django_db
def test_batch_assessment_page_renders(authenticated_client, user):
    """The standalone batch assessment page still renders.

    It is no longer linked from any template, but the URL remains reachable
    and `moz-phab` may hand it to developers.
    """
    response = authenticated_client.get(
        reverse("uplift-request-page"), {"revisions": "100,200"}
    )

    assert response.status_code == 200, "The batch assessment page should render."
    assert response.context_data["revision_ids"] == [100, 200], (
        "The page should parse the requested revision IDs."
    )


@pytest.mark.django_db
def test_batch_assessment_page_rejects_bad_revisions(authenticated_client, user):
    """Malformed revision IDs redirect rather than erroring."""
    response = authenticated_client.get(
        reverse("uplift-request-page"), {"revisions": "not-a-revision"}
    )

    assert response.status_code == 302, "Invalid revision IDs should redirect."
