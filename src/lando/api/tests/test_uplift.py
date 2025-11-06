import json
import subprocess
from unittest import mock

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from packaging.version import (
    Version,
)

from lando.api.legacy.uplift import (
    create_uplift_bug_update_payload,
    parse_milestone_version,
)
from lando.api.tests.test_landings import PATCH_CHANGE_MISSING_CONTENT
from lando.main.models import JobStatus, PermanentFailureException
from lando.main.models.uplift import (
    LowMediumHighChoices,
    RevisionUpliftJob,
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
    YesNoChoices,
    YesNoUnknownChoices,
)
from lando.main.scm import SCM_TYPE_GIT
from lando.ui.legacy.forms import (
    UpliftAssessmentForm,
)
from lando.ui.legacy.revisions import uplift_context_for_revision

MILESTONE_TEST_CONTENTS_1 = """
# Holds the current milestone.
# Should be in the format of
#
#    x.x.x
#    x.x.x.x
#    x.x.x+
#
# Referenced by build/moz.configure/init.configure.
# Hopefully I'll be able to automate replacement of *all*
# hardcoded milestones in the tree from these two files.
#--------------------------------------------------------

84.0a1
"""

MILESTONE_TEST_CONTENTS_2 = """
# Holds the current milestone.
# Should be in the format of
#
#    x.x.x
#    x.x.x.x
#    x.x.x+
#
# Referenced by build/moz.configure/init.configure.
# Hopefully I'll be able to automate replacement of *all*
# hardcoded milestones in the tree from these two files.
#--------------------------------------------------------

105.0
"""


def test_parse_milestone_version():
    assert parse_milestone_version(MILESTONE_TEST_CONTENTS_1) == Version(
        "84.0a1"
    ), "Test milestone file 1 should have 84 as major milestone version."

    assert parse_milestone_version(MILESTONE_TEST_CONTENTS_2) == Version(
        "105.0"
    ), "Test milestone file 2 should have 84 as major milestone version."

    bad_milestone_contents = "blahblahblah"
    with pytest.raises(ValueError, match=bad_milestone_contents):
        parse_milestone_version(bad_milestone_contents)


@pytest.mark.django_db
def test_uplift_creation_uses_existing_revisions_and_links_jobs(
    authenticated_client, user, repo_mc, create_patch_revision, normal_patch, phabdouble
):
    """Uplift creation endpoint happy-path test."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    # Create two target repos.
    repo_a = repo_mc(scm_type=SCM_TYPE_GIT, name="firefox-beta", approval_required=True)
    repo_b = repo_mc(
        scm_type=SCM_TYPE_GIT, name="firefox-release", approval_required=True
    )

    # Create the revisions with `456` before `123` to ensure the passed
    # ordering in `source_revisions` is preserved instead of the
    # default queryset ordering.
    revisions_created = [
        create_patch_revision(456, patch=normal_patch(1)),
        create_patch_revision(123, patch=normal_patch(0)),
    ]
    revisions_ordered = reversed(revisions_created)

    url = reverse("uplift-page")
    form_data = {
        "source_revisions": [revision.revision_id for revision in revisions_ordered],
        "repositories": [repo_a.name, repo_b.name],
    }
    form_data |= CREATE_FORM_DATA

    # POST form to Lando. Use D456 as the referrer since it is the tip.
    response = authenticated_client.post(url, data=form_data, HTTP_REFERER="/D456")

    # Redirect + success message.
    assert response.status_code == 302, "Successful creation should return 302."
    assert (
        response["Location"] == "/D456"
    ), "Successful creation should redirect to tip revision."
    messages = list(get_messages(response.wsgi_request))
    assert any(
        "Uplift request queued." in str(message) for message in messages
    ), f"Successful creation should flash success: {messages=}"

    # Assessment created and owned by the requester.
    assert (
        UpliftAssessment.objects.count() == 1
    ), "A new `UpliftAssessment` should be created."
    assessment = UpliftAssessment.objects.get()
    assert assessment.user_id == user.id, "New assessment should belong to the user."

    # Parent request created and linked to assessment.
    assert (
        UpliftSubmission.objects.count() == 1
    ), "New uplift request should be created."
    submission = UpliftSubmission.objects.select_related(
        "assessment", "requested_by"
    ).get()
    assert (
        submission.assessment_id == assessment.id
    ), "Uplift request should be associated with assessment."
    assert (
        submission.requested_by_id == user.id
    ), "Uplift request should belong to the user."
    assert submission.requested_revision_ids == [
        123,
        456,
    ], "Both revisions should be tracked, in the correct order, in uplift request."

    jobs = list(
        UpliftJob.objects.select_related("target_repo").filter(submission=submission)
    )
    assert len(jobs) == 2, "Two uplift jobs should be created."
    assert all(
        job.status == JobStatus.SUBMITTED for job in jobs
    ), "Newly created uplift jobs should be submitted for processing."
    repo_names = sorted(job.target_repo.name for job in jobs)
    assert repo_names == [
        repo_a.name,
        repo_b.name,
    ], "Both requested repos should have an uplift job."

    assert (
        list(
            submission.uplift_jobs.order_by("target_repo__name").values_list(
                "target_repo__name", flat=True
            )
        )
        == repo_names
    ), "Querying uplift request for jobs should show one for each repo."

    for job in jobs:
        job_rev_ids = list(job.revisions.values_list("revision_id", flat=True))
        assert job_rev_ids == [
            123,
            456,
        ], "Each job should reference the requested Revision."

        for idx, revision in enumerate(revisions_ordered):
            thru = RevisionUpliftJob.objects.get(uplift_job=job, revision=revision)
            assert thru.index == idx, "Single-item stack should be indexed."


@pytest.mark.django_db
def test_uplift_creation_fails_when_revisions_missing(
    authenticated_client, repo_mc, user, phabdouble
):
    """Test uplift creation endpoint behaviour without previous landing."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    repo_a = repo_mc(scm_type=SCM_TYPE_GIT, name="firefox-beta", approval_required=True)
    repo_b = repo_mc(
        scm_type=SCM_TYPE_GIT, name="firefox-release", approval_required=True
    )

    url = reverse("uplift-page")

    # NOTE: We intentionally DO NOT create a Revision(revision_id=1234) here.

    form_data = {
        "source_revisions": [123, 456],
        "repositories": [repo_a.name, repo_b.name],
    }
    form_data |= CREATE_FORM_DATA

    response = authenticated_client.post(url, data=form_data, HTTP_REFERER="/D1234")

    assert (
        response.status_code == 302
    ), "Submission missing requested revisions should redirect with error."
    messages = list(get_messages(response.wsgi_request))
    assert any(
        "is not one of the available choices" in str(message) for message in messages
    ), f"Should reject with message about no previous landing: {messages=}"

    assert (
        UpliftAssessment.objects.count() == 0
    ), "Failed submission should not create an assessment."
    assert (
        UpliftSubmission.objects.count() == 0
    ), "Failed submission should not create an uplift submission."
    assert (
        UpliftJob.objects.count() == 0
    ), "Failed submission should not enqueue uplift jobs."
    assert (
        RevisionUpliftJob.objects.count() == 0
    ), "Failed submission should not populate through rows."


def test_create_uplift_bug_update_payload():
    bug = {
        "cf_status_firefox100": "---",
        "id": 123,
        "keywords": [],
        "whiteboard": "[checkin-needed-beta]",
    }
    payload = create_uplift_bug_update_payload(
        bug, "beta", 100, "cf_status_firefox{milestone}"
    )

    assert payload["ids"] == [123], "Passed bug ID should be present in the payload."
    assert (
        payload["whiteboard"] == ""
    ), "checkin-needed flag should be removed from whiteboard."
    assert (
        payload["cf_status_firefox100"] == "fixed"
    ), "Custom tracking flag should be set to `fixed`."

    bug = {
        "cf_status_firefox100": "---",
        "id": 123,
        "keywords": ["leave-open"],
        "whiteboard": "[checkin-needed-beta]",
    }
    payload = create_uplift_bug_update_payload(
        bug, "beta", 100, "cf_status_firefox{milestone}"
    )

    assert (
        "cf_status_firefox100" not in payload
    ), "Status should not have been set with `leave-open` keyword on bug."


@pytest.mark.django_db
def test_to_conduit_json_transforms_fields(user):
    instance = UpliftAssessment.objects.create(
        user=user,
        user_impact="Impact",
        covered_by_testing=YesNoUnknownChoices.YES,
        fix_verified_in_nightly=YesNoChoices.NO,
        needs_manual_qe_testing=YesNoChoices.YES,
        qe_testing_reproduction_steps="Steps",
        risk_associated_with_patch=LowMediumHighChoices.HIGH,
        risk_level_explanation="Explanation",
        string_changes="Changes",
        is_android_affected=YesNoUnknownChoices.UNKNOWN,
    )

    conduit_dict = instance.to_conduit_json()
    assert isinstance(conduit_dict, dict), "`to_conduit_json` should return a `dict`."
    assert (
        conduit_dict["User impact if declined"] == "Impact"
    ), "`user_impact` field should not be transformed."
    assert (
        conduit_dict["Code covered by automated testing"] is True
    ), "`Yes` should be converted to `True`."
    assert (
        conduit_dict["Fix verified in Nightly"] is False
    ), "`No` should be converted to `False`."
    assert (
        conduit_dict["Needs manual QE test"] is True
    ), "`Yes` should be converted to `True`."
    assert (
        conduit_dict["Is Android affected?"] is False
    ), "`Unknown` should be converted to `False`."
    assert (
        conduit_dict["Risk associated with taking this patch"] == "high"
    ), "Text choice should be converted to `str`."

    conduit_str = instance.to_conduit_json_str()

    assert (
        conduit_str
        == '{"User impact if declined": "Impact", "Code covered by automated testing": true, "Fix verified in Nightly": false, "Needs manual QE test": true, "Steps to reproduce for manual QE testing": "Steps", "Risk associated with taking this patch": "high", "Explanation of risk level": "Explanation", "String changes made/needed": "Changes", "Is Android affected?": false}'
    ), "`to_conduit_json_str` should return dict as a string."


CREATE_FORM_DATA = {
    "user_impact": "Initial impact description.",
    "covered_by_testing": "yes",
    "fix_verified_in_nightly": "no",
    "needs_manual_qe_testing": "no",
    "qe_testing_reproduction_steps": "",
    "risk_associated_with_patch": "low",
    "risk_level_explanation": "Low risk because it's well-tested.",
    "string_changes": "No changes.",
    "is_android_affected": "no",
}

UPDATED_FORM_DATA = {
    "user_impact": "Updated impact after more testing.",
    "covered_by_testing": "no",
    "fix_verified_in_nightly": "yes",
    "needs_manual_qe_testing": "yes",
    "qe_testing_reproduction_steps": "Steps go here.",
    "risk_associated_with_patch": "medium",
    "risk_level_explanation": "Medium risk due to timing.",
    "string_changes": "Yes, minor updates.",
    "is_android_affected": "yes",
}


@mock.patch("lando.ui.legacy.revisions.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db
def test_patch_assessment_creates_and_updates(
    mock_apply_async, authenticated_client, user, phabdouble
):
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    url = reverse("uplift-assessment-page", args=[1234])

    form = UpliftAssessmentForm(data=CREATE_FORM_DATA)
    assert form.is_valid(), f"Form was invalid: {form.errors.as_json()}"

    # Submit the form for a revision.
    response = authenticated_client.post(
        url, data=CREATE_FORM_DATA, HTTP_REFERER="/D1234"
    )
    assert (
        response.status_code == 302
    ), "Updating assessment form should redirect back to referrer."

    # Check that a new response was created.
    responses = UpliftAssessment.objects.all()
    assert responses.count() == 1, "Updating a form should result in a single form."

    response_obj = responses.first()
    assert (
        response_obj.user_impact == CREATE_FORM_DATA["user_impact"]
    ), "`user_impact` field should match the initial value."

    revision = UpliftRevision.objects.get()
    assert revision.revision_id == 1234, "Revision ID should match initial value."
    assert (
        revision.assessment == response_obj
    ), "Response object for the revision should match the queried model."

    # Assert Celery task was called.
    assert (
        mock_apply_async.call_count == 1
    ), "`set_uplift_request_form_on_revision` should be called."
    _, kwargs = mock_apply_async.call_args
    revision_id, conduit_json_str, user_id = kwargs["args"]

    assert (
        revision_id == 1234
    ), "Revision ID for `set_uplift_request_form_on_revision` should match expected."
    assert isinstance(
        conduit_json_str, str
    ), "Uplift form be JSON string from `to_conduit_json_str()`."
    assert (
        user_id == user.id
    ), "User ID for `set_uplift_request_form_on_revision` should match expected."

    # Submit the form for a revision which already has a completed form.
    response = authenticated_client.post(
        url, data=UPDATED_FORM_DATA, HTTP_REFERER="/D1234"
    )
    assert (
        response.status_code == 302
    ), "Updating assessment form should redirect back to referrer."

    # Check that a new response was created.
    responses = UpliftAssessment.objects.all()
    assert responses.count() == 1, "Updating a form should result in a single form."

    updated_response_obj = responses.first()
    assert (
        updated_response_obj.user_impact == UPDATED_FORM_DATA["user_impact"]
    ), "User impact should be updated to a new value."

    revision.refresh_from_db()
    assert (
        revision.assessment == updated_response_obj
    ), "Revision should point to the new response."

    # Assert Celery task was called again.
    assert (
        mock_apply_async.call_count == 2
    ), "`set_uplift_request_form_on_revision` should be called."
    _, kwargs = mock_apply_async.call_args
    revision_id, conduit_json_str, user_id = kwargs["args"]

    assert (
        revision_id == 1234
    ), "Revision ID for `set_uplift_request_form_on_revision` should match expected."
    assert isinstance(
        conduit_json_str, str
    ), "Uplift form be JSON string from `to_conduit_json_str()`."
    assert (
        user_id == user.id
    ), "User ID for `set_uplift_request_form_on_revision` should match expected."


@mock.patch("lando.ui.legacy.revisions.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db
def test_patch_assessment_updates_in_place(
    mock_apply_async, authenticated_client, user, phabdouble
):
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    url = reverse("uplift-assessment-page", args=[1234])

    authenticated_client.post(url, data=CREATE_FORM_DATA, HTTP_REFERER="/D1234")
    original_assessment = UpliftAssessment.objects.get()
    original_pk = original_assessment.pk

    response = authenticated_client.post(
        url, data=UPDATED_FORM_DATA, HTTP_REFERER="/D1234"
    )

    assert response.status_code == 302, "Update should redirect to referrer."
    assert (
        UpliftAssessment.objects.count() == 1
    ), "Assessment update should not create additional rows."

    updated_assessment = UpliftAssessment.objects.get()
    assert (
        updated_assessment.pk == original_pk
    ), "Assessment should be updated in place, not replaced."
    assert (
        updated_assessment.user_impact == UPDATED_FORM_DATA["user_impact"]
    ), "Updated assessment should reflect new values."

    mock_apply_async.assert_called()


@mock.patch("lando.ui.legacy.revisions.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db
def test_patch_assessment_form_invalid(
    mock_apply_async, authenticated_client, user, phabdouble
):
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    url = reverse("uplift-assessment-page", args=[1234])

    # Form is invalid because required fields are missing or invalid.
    invalid_data = {
        # Required field left empty.
        "user_impact": "",
        "covered_by_testing": "yes",
        "fix_verified_in_nightly": "no",
        "needs_manual_qe_testing": "yes",
        # Required as `needs_manual_qe_testing` is `yes`.
        "qe_testing_reproduction_steps": "",
        "risk_associated_with_patch": "low",
        "risk_level_explanation": "Low risk because it's well-tested.",
        "string_changes": "No changes.",
        "is_android_affected": "no",
    }

    response = authenticated_client.post(url, data=invalid_data, HTTP_REFERER="/D1234")

    assert response.status_code == 302, "Submission should redirect on error."
    assert (
        UpliftAssessment.objects.count() == 0
    ), "Assessment should not be saved on error."
    assert (
        UpliftRevision.objects.count() == 0
    ), "Assessment should not be associated with a revision."

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    for bad_field in ("qe_testing_reproduction_steps", "user_impact"):
        assert any(
            bad_field in message for message in messages
        ), f"Validation message not sent for `{bad_field}`: {messages=}"

    assert mock_apply_async.call_count == 0, "Uplift form task should not be called."


@mock.patch("lando.ui.legacy.revisions.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db
def test_link_assessment_links_existing_form(
    mock_apply_async, authenticated_client, user, phabdouble
):
    """Linking endpoint should tie an existing assessment to a revision."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    assessment = UpliftAssessment.objects.create(user=user, **CREATE_FORM_DATA)
    url = reverse("uplift-assessment-link-page", args=[5678])

    response = authenticated_client.post(
        url,
        data={"assessment": assessment.pk},
        HTTP_REFERER="/D5678",
    )

    assert response.status_code == 302, "Successful link should redirect to referrer."
    assert (
        response["Location"] == "/D5678"
    ), "Linking should return to the revision page."
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any(
        "Linked existing assessment to this revision." in message
        for message in messages
    ), f"Successful link should flash confirmation: {messages=}"

    revision_link = UpliftRevision.objects.get()
    assert (
        revision_link.revision_id == 5678
    ), "Revision link should target the requested revision."
    assert (
        revision_link.assessment_id == assessment.id
    ), "Revision should be associated with the selected assessment."

    assessment.refresh_from_db()
    assert (
        assessment.revisions.count() == 1
    ), "Assessment should now be linked to exactly one revision."

    assert mock_apply_async.call_count == 1, "Celery task should update Phabricator."
    _, kwargs = mock_apply_async.call_args
    task_revision_id, conduit_json_str, user_id = kwargs["args"]
    assert (
        task_revision_id == 5678
    ), "Celery task should publish the linked revision ID."
    assert isinstance(
        conduit_json_str, str
    ), "Celery task should receive the serialized assessment payload."
    assert user_id == user.id, "Celery task should run under the submitting user."


@mock.patch("lando.ui.legacy.revisions.set_uplift_request_form_on_revision.apply_async")
@pytest.mark.django_db
def test_link_assessment_replaces_existing_form(
    mock_apply_async, authenticated_client, user, phabdouble
):
    """Link endpoint should flash replacement message when swapping assessments."""
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    previous_assessment = UpliftAssessment.objects.create(user=user, **CREATE_FORM_DATA)
    replacement_assessment = UpliftAssessment.objects.create(
        user=user,
        # Ensure unique data to avoid accidental equality with previous form fields.
        user_impact="Affects nightly users.",
        covered_by_testing="no",
        fix_verified_in_nightly="no",
        needs_manual_qe_testing="no",
        qe_testing_reproduction_steps="",
        risk_associated_with_patch="medium",
        risk_level_explanation="Moderate risk because coverage incomplete.",
        string_changes="No string changes.",
        is_android_affected="yes",
    )

    # Pre-link the previous assessment to the revision.
    UpliftRevision.objects.create(
        revision_id=6789,
        assessment=previous_assessment,
    )

    url = reverse("uplift-assessment-link-page", args=[6789])
    response = authenticated_client.post(
        url,
        data={"assessment": replacement_assessment.pk},
        HTTP_REFERER="/D6789",
    )

    assert response.status_code == 302, "Successful replacement should redirect."
    assert response["Location"] == "/D6789", "Replacement should return to revision."
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any(
        "Replaced linked assessment for this revision." in message
        for message in messages
    ), f"Replacement action should flash confirmation: {messages=}"

    revision_link = UpliftRevision.objects.get(revision_id=6789)
    assert (
        revision_link.assessment_id == replacement_assessment.id
    ), "Revision should link to the replacement assessment."

    mock_apply_async.assert_called_once()
    _, kwargs = mock_apply_async.call_args
    task_revision_id, conduit_json_str, user_id = kwargs["args"]
    assert task_revision_id == 6789, "Celery task should receive revision ID."
    assert user_id == user.id, "Celery task should use the requesting user's identity."
    assert isinstance(
        conduit_json_str, str
    ), "Celery task should receive serialized payload."


@pytest.mark.django_db
def test_uplift_worker_applies_patches_and_creates_uplift_revision_success_git(
    repo_mc,
    user,
    uplift_worker,
    create_patch_revision,
    normal_patch,
    monkeypatch,
    make_uplift_job_with_revisions,
    mock_uplift_email_tasks,
):
    def mock_write_update_commits(commits):
        def _write_uplift_commits(job_arg, base_rev, env, output_path):
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "commits": commits,
                    },
                    fh,
                )

        return _write_uplift_commits

    repo = repo_mc(SCM_TYPE_GIT, name="firefox-beta", approval_required=True)

    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=normal_patch(1)),
    ]

    mock_success_task, mock_failure_task = mock_uplift_email_tasks

    # Two small valid patches.
    job = make_uplift_job_with_revisions(repo, user, revisions)
    mock_task = mock.MagicMock()
    monkeypatch.setattr(
        "lando.api.legacy.workers.uplift_worker.set_uplift_request_form_on_revision",
        mock_task,
    )

    # Let update_repo/apply_patch run for real and only mock moz-phab uplift to return new tip D-IDs.
    monkeypatch.setattr(
        uplift_worker,
        "run_moz_phab_uplift",
        mock_write_update_commits(
            [
                {"rev_id": 4567},
                {"rev_id": 4568},
            ]
        ),
    )

    # Capture the current HEAD to validate it advanced.
    old_head = repo.scm.head_ref()

    assert uplift_worker.run_job(job), "Job should have completed successfully."

    job.refresh_from_db()
    expected_task_args = (
        job.created_revision_ids[-1],
        job.submission.assessment.to_conduit_json_str(),
        user.id,
    )
    mock_task.apply_async.assert_called_once_with(args=expected_task_args)
    assert (
        job.status == JobStatus.LANDED
    ), "Successful uplift job should transition to LANDED."
    assert job.created_revision_ids == [
        4567,
        4568,
    ], "Successful uplift job should store all created revision IDs."

    # Validate that HEAD changed after applying patches locally.
    new_head = repo.scm.head_ref()
    assert (
        new_head != old_head
    ), "Repository HEAD should have advanced after applying patches."

    # Validate that UpliftRevision objects are created and linked.
    assert (
        UpliftRevision.objects.count() == 1
    ), "Successful uplift job should create a single UpliftRevision link."
    ur = UpliftRevision.objects.get()
    assert (
        ur.revision_id == 4568
    ), "Created UpliftRevision should point to the latest revision ID."
    assert (
        ur.assessment_id == job.submission.assessment_id
    ), "Created UpliftRevision should link back to the original assessment."

    # Mock `moz-phab uplift` again with new created commits.
    monkeypatch.setattr(
        uplift_worker,
        "run_moz_phab_uplift",
        mock_write_update_commits(
            [
                {"rev_id": 5000},
                {"rev_id": 5001},
            ]
        ),
    )

    job.refresh_from_db()
    job.status = JobStatus.SUBMITTED
    job.save(update_fields=["status"])

    assert uplift_worker.run_job(job), "Re-running job should still succeed."

    mock_success_task.apply_async.assert_called()
    mock_failure_task.apply_async.assert_not_called()

    args = mock_success_task.apply_async.call_args[1]["args"]
    assert args[0] == user.email
    assert args[1] == (repo.short_name or repo.name)
    assert args[3] == [
        5000,
        5001,
    ], "Revision identifiers should be in the correct order."
    assert (
        mock_task.apply_async.call_count == 2
    ), "Celery task should be dispatched on each successful run."

    expected_task_args = (
        job.created_revision_ids[-1],
        job.submission.assessment.to_conduit_json_str(),
        user.id,
    )
    assert mock_task.apply_async.call_args_list[-1].kwargs == {
        "args": expected_task_args
    }, "Celery task should be called with latest revision metadata."

    job.refresh_from_db()
    assert job.created_revision_ids == [
        5000,
        5001,
    ], "Re-running job should leave created_revision_ids unchanged."
    assert (
        UpliftRevision.objects.count() == 2
    ), "Re-running job should create a second UpliftRevision record."


@pytest.mark.django_db
def test_create_uplift_revisions_invokes_cli_and_returns_response(
    repo_mc,
    user,
    uplift_worker,
    create_patch_revision,
    normal_patch,
    monkeypatch,
    make_uplift_job_with_revisions,
):
    repo = repo_mc(SCM_TYPE_GIT, name="firefox-release", approval_required=True)

    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=normal_patch(1)),
    ]
    job = make_uplift_job_with_revisions(repo, user, revisions)

    api_key = user.profile.phabricator_api_key
    base_revision = "abcd1234"

    expected_response = {"commits": [{"rev_id": 9001}]}

    captured_call = {}

    def _capture_run(job_arg, base_rev_arg, env_arg, output_path_arg):
        captured_call["job"] = job_arg
        captured_call["base_revision"] = base_rev_arg
        captured_call["env"] = env_arg
        captured_call["output_path"] = output_path_arg
        with open(output_path_arg, "w", encoding="utf-8") as fh:
            json.dump(expected_response, fh)

    monkeypatch.setattr(uplift_worker, "run_moz_phab_uplift", _capture_run)

    response = uplift_worker.create_uplift_revisions(job, api_key, base_revision)

    assert (
        response == expected_response
    ), "`create_uplift_revisions` should return the JSON read from the output file."
    assert (
        captured_call
    ), "`create_uplift_revisions` should invoke `run_moz_phab_uplift`."
    assert (
        captured_call["job"] == job
    ), "`run_moz_phab_uplift` should be called with the uplift job."
    assert (
        captured_call["base_revision"] == base_revision
    ), "`run_moz_phab_uplift` should receive the base revision."
    assert (
        captured_call["env"]["MOZPHAB_PHABRICATOR_API_TOKEN"] == api_key
    ), "`run_moz_phab_uplift` should set the API key in the environment."


@pytest.mark.django_db
def test_create_uplift_revisions_invalid_json_marks_job_failed(
    repo_mc,
    user,
    uplift_worker,
    create_patch_revision,
    normal_patch,
    monkeypatch,
    make_uplift_job_with_revisions,
):
    repo = repo_mc(SCM_TYPE_GIT, name="firefox-release", approval_required=True)
    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=normal_patch(1)),
    ]
    job = make_uplift_job_with_revisions(repo, user, revisions)

    api_key = user.profile.phabricator_api_key

    def _write_invalid_json(job_arg, base_rev_arg, env_arg, output_path_arg):
        with open(output_path_arg, "w", encoding="utf-8") as fh:
            fh.write("not-json")

    monkeypatch.setattr(uplift_worker, "run_moz_phab_uplift", _write_invalid_json)

    with pytest.raises(PermanentFailureException):
        uplift_worker.create_uplift_revisions(job, api_key, "abcd1234")

    job.refresh_from_db()
    assert job.status == JobStatus.FAILED, "Invalid JSON output should fail the job."


@pytest.mark.django_db
def test_run_moz_phab_uplift_invokes_subprocess_with_expected_args(
    repo_mc,
    user,
    uplift_worker,
    create_patch_revision,
    normal_patch,
    make_uplift_job_with_revisions,
    monkeypatch,
    tmp_path,
):
    repo = repo_mc(SCM_TYPE_GIT, name="firefox-beta", approval_required=True)
    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=normal_patch(1)),
    ]
    job = make_uplift_job_with_revisions(repo, user, revisions)

    env = {"MOZPHAB_PHABRICATOR_API_TOKEN": user.profile.phabricator_api_key}
    output_path = tmp_path / "uplift.json"
    base_revision = "abcd1234"

    fake_run = mock.MagicMock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(subprocess, "run", fake_run)

    uplift_worker.run_moz_phab_uplift(
        job,
        base_revision,
        env,
        str(output_path),
    )

    fake_run.assert_called_once()
    called_cmd = fake_run.call_args.args[0]
    assert called_cmd[:5] == [
        "moz-phab",
        "uplift",
        "--yes",
        "--no-rebase",
        "--output-file",
    ], "`run_moz_phab_uplift` should call moz-phab uplift with no prompts or rebase."
    expected_repo_identifier = repo.short_name or repo.name
    assert called_cmd[6:] == [
        "--train",
        expected_repo_identifier,
        base_revision,
        "HEAD",
    ], "`run_moz_phab_uplift` should include repo and revisions in the command."
    assert (
        fake_run.call_args.kwargs["cwd"] == repo.system_path
    ), "`run_moz_phab_uplift` should use the repo path as the cwd."
    assert (
        fake_run.call_args.kwargs["env"] == env
    ), "`run_moz_phab_uplift` should forward the prepared environment."
    assert (
        fake_run.call_args.kwargs["encoding"] == "utf-8"
    ), "`run_moz_phab_uplift` should request UTF-8 encoding."


@pytest.mark.django_db
def test_uplift_worker_mozphab_failure_marks_failed(
    repo_mc,
    user,
    uplift_worker,
    create_patch_revision,
    normal_patch,
    monkeypatch,
    make_uplift_job_with_revisions,
    mock_uplift_email_tasks,
):
    repo = repo_mc(SCM_TYPE_GIT, name="firefox-beta", approval_required=True)

    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=normal_patch(1)),
    ]

    # Two small valid patches.
    job = make_uplift_job_with_revisions(repo, user, revisions)

    mock_success_task, mock_failure_task = mock_uplift_email_tasks

    # Allow real update_repo/apply_patch; make `moz-phab uplift` throw.
    def _uplift_fail(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=2,
            cmd=["moz-phab", "uplift", "--yes", "--no-rebase"],
            output="",
            stderr="boom",
        )

    # Patch subprocess.run inside the worker's `run_moz_phab_uplift`.
    monkeypatch.setattr(subprocess, "run", _uplift_fail)

    assert not uplift_worker.run_job(job), "Job should not complete successfully."

    job.refresh_from_db()
    assert (
        job.status == JobStatus.FAILED
    ), "Job should be marked FAILED on moz-phab error."
    assert (
        UpliftRevision.objects.count() == 0
    ), "No UpliftRevision should be created on failure."
    mock_failure_task.apply_async.assert_called_once()
    mock_success_task.apply_async.assert_not_called()


@pytest.mark.django_db
def test_uplift_worker_apply_patch_invalid_patch_raises_and_does_not_land(
    repo_mc,
    user,
    uplift_worker,
    create_patch_revision,
    normal_patch,
    monkeypatch,
    make_uplift_job_with_revisions,
    mock_uplift_email_tasks,
):
    repo = repo_mc(SCM_TYPE_GIT, name="firefox-esr", approval_required=True)

    # Create a job where one revision has a bad patch.
    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=PATCH_CHANGE_MISSING_CONTENT),
    ]
    job = make_uplift_job_with_revisions(repo, user, revisions)

    mock_success_task, mock_failure_task = mock_uplift_email_tasks

    # Ensure run_moz_phab_uplift won't be triggered if apply_patch fails.
    mocked_run_moz = mock.MagicMock()
    monkeypatch.setattr(uplift_worker, "run_moz_phab_uplift", mocked_run_moz)

    assert not uplift_worker.run_job(job), "Job should not complete successfully."

    job.refresh_from_db()
    assert (
        job.status != JobStatus.LANDED
    ), "Job must not be LANDED when apply_patch fails."
    assert (
        UpliftRevision.objects.count() == 0
    ), "Apply-patch failure should not create UpliftRevision records."
    assert (
        job.created_revision_ids == []
    ), "Apply-patch failure should leave created_revision_ids empty."

    mock_failure_task.apply_async.assert_called_once()
    mock_success_task.apply_async.assert_not_called()
    mocked_run_moz.assert_not_called()

    failure_args = mock_failure_task.apply_async.call_args[1]["args"]
    assert failure_args[0] == user.email
    assert failure_args[1] == (repo.short_name or repo.name)
    assert failure_args[2], "Job URL should be included for patch failures."
    assert failure_args[3], "Failure reason should be included for patch failures."


@pytest.mark.django_db
def test_uplift_context_for_revision_returns_original_and_uplifted_requests(
    repo_mc, user, create_patch_revision, normal_patch, make_uplift_job_with_revisions
):
    repo = repo_mc(SCM_TYPE_GIT, name="firefox-beta", approval_required=True)

    revisions = [
        create_patch_revision(0, patch=normal_patch(0)),
        create_patch_revision(1, patch=normal_patch(1)),
    ]
    job = make_uplift_job_with_revisions(repo, user, revisions)
    submission = job.submission

    original_revision_id = revisions[0].revision_id
    uplifted_revision_id = 9876

    UpliftRevision.objects.create(
        assessment=submission.assessment,
        revision_id=uplifted_revision_id,
    )

    other_repo = repo_mc(SCM_TYPE_GIT, name="firefox-esr", approval_required=True)
    other_revision = create_patch_revision(2, patch=normal_patch(2))
    make_uplift_job_with_revisions(other_repo, user, [other_revision])

    requested_qs = uplift_context_for_revision(original_revision_id)
    uplifted_qs = uplift_context_for_revision(uplifted_revision_id)

    assert list(requested_qs) == [
        submission
    ], "Querying with original revision ID should find the uplift request."
    assert list(uplifted_qs) == [
        submission
    ], "Querying with uplifted revision ID should find the uplift request."
