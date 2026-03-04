import json
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from lando.main.management.commands.export_to_bigquery import (
    RepoExporter,
    RevisionUpliftJobExporter,
    UpliftAssessmentExporter,
    UpliftJobExporter,
    UpliftRevisionExporter,
    UpliftSubmissionExporter,
    datetime_to_timestamp,
    get_cutoff_timestamp,
    incoming_table_id,
    sql_table_id,
)
from lando.main.models.uplift import (
    RevisionUpliftJob,
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
)


@pytest.mark.parametrize(
    "dt,expected,msg",
    [
        (None, None, "Should return `None` for `None` input."),
        (
            datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc),
            1705321845,
            "Should convert `datetime` to Unix timestamp.",
        ),
        (
            datetime(2024, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc),
            1705321845,
            "Should truncate microseconds.",
        ),
    ],
)
def test_datetime_to_timestamp(dt, expected, msg):
    result = datetime_to_timestamp(dt)
    assert result == expected, msg


def test_sql_table_id_formats_table_reference():
    table = MagicMock()
    table.project = "my-project"
    table.dataset_id = "my_dataset"
    table.table_id = "my_table"

    result = sql_table_id(table)

    assert (
        result == "my-project.my_dataset.my_table"
    ), "`sql_table_id` should output in expected format."


def test_incoming_table_id_appends_incoming_suffix():
    result = incoming_table_id("project.dataset.table")
    assert (
        result == "project.dataset.table_incoming"
    ), "Should append `_incoming` suffix to table ID."


@pytest.mark.django_db
def test_transform_repo(make_repo):
    repo = make_repo(1)

    exporter = RepoExporter()
    result = exporter.transform(repo)

    assert result["id"] == repo.id, "Should include `id`."
    assert result["name"] == "repo-1", "Should include `name`."
    assert result["short_name"] == repo.short_name, "Should include `short_name`."
    assert result["url"] == repo.url, "Should include `url`."
    assert result["scm_type"] == "git", "Should include `scm_type`."
    assert (
        result["is_phabricator_repo"] is True
    ), "Should include `is_phabricator_repo`."
    assert result["is_try"] is False, "Should include `is_try`."
    assert result["automation_enabled"] is False, "Should include `automation_enabled`."
    assert result["created_at"] is not None, "Should convert `created_at` to timestamp."
    assert result["updated_at"] is not None, "Should convert `updated_at` to timestamp."


@pytest.mark.django_db
def test_transform_uplift_assessment():
    user = User.objects.create_user(username="testuser", email="test@example.com")
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="high",
        covered_by_testing="yes",
        fix_verified_in_nightly="no",
        needs_manual_qe_testing="yes",
        qe_testing_reproduction_steps="Step 1, Step 2",
        risk_associated_with_patch="low",
        risk_level_explanation="Simple change",
        string_changes="none",
        is_android_affected="yes",
    )

    exporter = UpliftAssessmentExporter()
    result = exporter.transform(assessment)

    assert result["id"] == assessment.id, "Should include `id`."
    assert result["user_id"] == user.id, "Should include `user_id`."
    assert result["user_impact"] == "high", "Should include `user_impact`."
    assert result["covered_by_testing"] == "yes", "Should include `covered_by_testing`."
    assert (
        result["fix_verified_in_nightly"] == "no"
    ), "Should include `fix_verified_in_nightly`."
    assert (
        result["needs_manual_qe_testing"] == "yes"
    ), "Should include `needs_manual_qe_testing`."
    assert (
        result["qe_testing_reproduction_steps"] == "Step 1, Step 2"
    ), "Should include `qe_testing_reproduction_steps`."
    assert (
        result["risk_associated_with_patch"] == "low"
    ), "Should include `risk_associated_with_patch`."
    assert (
        result["risk_level_explanation"] == "Simple change"
    ), "Should include `risk_level_explanation`."
    assert result["string_changes"] == "none", "Should include `string_changes`."
    assert (
        result["is_android_affected"] == "yes"
    ), "Should include `is_android_affected`."
    assert result["created_at"] is not None, "Should convert `created_at` to timestamp."
    assert result["updated_at"] is not None, "Should convert `updated_at` to timestamp."


@pytest.mark.django_db
def test_transform_uplift_revision():
    user = User.objects.create_user(username="testuser", email="test@example.com")
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="medium",
        risk_level_explanation="low risk",
        string_changes="none",
    )
    revision = UpliftRevision.objects.create(
        assessment=assessment,
        revision_id=12345,
    )

    exporter = UpliftRevisionExporter()
    result = exporter.transform(revision)

    assert result["id"] == revision.id, "Should include `id`."
    assert result["assessment_id"] == assessment.id, "Should include `assessment_id`."
    assert result["revision_id"] == 12345, "Should include `revision_id`."
    assert result["created_at"] is not None, "Should convert `created_at` to timestamp."
    assert result["updated_at"] is not None, "Should convert `updated_at` to timestamp."


@pytest.mark.django_db
def test_transform_uplift_submission():
    user = User.objects.create_user(username="testuser", email="test@example.com")
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="medium",
        risk_level_explanation="low risk",
        string_changes="none",
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user,
        assessment=assessment,
        requested_revision_ids=[100, 101, 102],
    )

    exporter = UpliftSubmissionExporter()
    result = exporter.transform(submission)

    assert result["id"] == submission.id, "Should include `id`."
    assert result["requested_by_id"] == user.id, "Should include `requested_by_id`."
    assert result["requested_revision_ids"] == [
        100,
        101,
        102,
    ], "Should include `requested_revision_ids`."
    assert result["assessment_id"] == assessment.id, "Should include `assessment_id`."
    assert result["created_at"] is not None, "Should convert `created_at` to timestamp."
    assert result["updated_at"] is not None, "Should convert `updated_at` to timestamp."


@pytest.mark.django_db
def test_transform_uplift_job(make_repo):
    user = User.objects.create_user(username="testuser", email="test@example.com")
    repo = make_repo(1)
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="medium",
        risk_level_explanation="low risk",
        string_changes="none",
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user,
        assessment=assessment,
        requested_revision_ids=[100, 101],
    )
    job = UpliftJob.objects.create(
        status="LANDED",
        landed_commit_id="abc123",
        requester_email="user@example.com",
        attempts=2,
        priority=1,
        duration_seconds=120,
        target_repo=repo,
        created_revision_ids=[200, 201],
        submission=submission,
    )

    exporter = UpliftJobExporter()
    result = exporter.transform(job)

    assert result["id"] == job.id, "Should include `id`."
    assert result["status"] == "LANDED", "Should include `status`."
    assert result["error"] == "", "Should include `error`."
    assert result["error_breakdown"] == {}, "Should include `error_breakdown`."
    assert result["landed_commit_id"] == "abc123", "Should include `landed_commit_id`."
    assert (
        result["requester_email"] == "user@example.com"
    ), "Should include `requester_email`."
    assert result["attempts"] == 2, "Should include `attempts`."
    assert result["priority"] == 1, "Should include `priority`."
    assert result["duration_seconds"] == 120, "Should include `duration_seconds`."
    assert result["target_repo_id"] == repo.id, "Should include `target_repo_id`."
    assert result["created_revision_ids"] == [
        200,
        201,
    ], "Should include `created_revision_ids`."
    assert result["submission_id"] == submission.id, "Should include `submission_id`."
    assert result["created_at"] is not None, "Should convert `created_at` to timestamp."
    assert result["updated_at"] is not None, "Should convert `updated_at` to timestamp."


@pytest.mark.django_db
def test_transform_revision_uplift_job(make_repo):
    user = User.objects.create_user(username="testuser", email="test@example.com")
    repo = make_repo(1)
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="medium",
        risk_level_explanation="low risk",
        string_changes="none",
    )
    submission = UpliftSubmission.objects.create(
        requested_by=user,
        assessment=assessment,
        requested_revision_ids=[100],
    )
    job = UpliftJob.objects.create(
        status="SUBMITTED",
        requester_email="user@example.com",
        target_repo=repo,
        submission=submission,
    )
    revision_uplift_job = RevisionUpliftJob.objects.create(
        uplift_job=job,
        revision=None,
        index=0,
    )

    exporter = RevisionUpliftJobExporter()
    result = exporter.transform(revision_uplift_job)

    assert result["id"] == revision_uplift_job.id, "Should include `id`."
    assert result["uplift_job_id"] == job.id, "Should include `uplift_job_id`."
    assert result["revision_id"] is None, "Should include `revision_id`."
    assert result["index"] == 0, "Should include `index`."
    assert result["created_at"] is not None, "Should convert `created_at` to timestamp."
    assert result["updated_at"] is not None, "Should convert `updated_at` to timestamp."


def test_get_cutoff_timestamp_full_export_returns_datetime_min():
    bq_client = MagicMock()

    result = get_cutoff_timestamp(bq_client, full_export=True, since_arg=None)

    assert result == datetime.min.replace(
        tzinfo=timezone.utc
    ), "Should return `datetime.min` (UTC) for full export."


@pytest.mark.parametrize(
    "since_arg,expected,msg",
    [
        (
            "2024-01-15T12:30:45+00:00",
            datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc),
            "Should parse ISO timestamp with timezone.",
        ),
        (
            "2024-01-15T12:30:45",
            datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc),
            "Should add UTC timezone to naive `datetime`.",
        ),
    ],
)
def test_get_cutoff_timestamp_parses_since_arg(since_arg, expected, msg):
    bq_client = MagicMock()

    result = get_cutoff_timestamp(bq_client, full_export=False, since_arg=since_arg)

    assert result == expected, msg


@pytest.mark.parametrize(
    "bq_return,expected,msg",
    [
        (
            datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc),
            "Should return timestamp from BigQuery.",
        ),
        (
            None,
            datetime.min.replace(tzinfo=timezone.utc),
            "Should return `datetime.min` (UTC) when BigQuery has no previous data.",
        ),
    ],
)
@patch("lando.main.management.commands.export_to_bigquery.get_last_run_timestamp")
def test_get_cutoff_timestamp_falls_back_to_bigquery(
    mock_get_last_run, bq_return, expected, msg
):
    bq_client = MagicMock()
    mock_get_last_run.return_value = bq_return

    result = get_cutoff_timestamp(bq_client, full_export=False, since_arg=None)

    assert result == expected, msg


@pytest.mark.django_db
@patch("lando.main.management.commands.export_to_bigquery.bigquery.Client")
def test_export_to_bigquery_output_file_writes_json_lines(mock_bq_client):
    # Create test data.
    user = User.objects.create_user(username="testuser", email="test@example.com")
    assessment = UpliftAssessment.objects.create(
        user=user,
        user_impact="high",
        covered_by_testing="yes",
        fix_verified_in_nightly="no",
        needs_manual_qe_testing="yes",
        qe_testing_reproduction_steps="Step 1, Step 2",
        risk_associated_with_patch="low",
        risk_level_explanation="Low risk.",
        string_changes="none",
        is_android_affected="yes",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "export.jsonl"
        stdout = StringIO()

        call_command(
            "export_to_bigquery",
            "--output-file",
            str(output_path),
            "--full",
            stdout=stdout,
        )

        # Verify the file was created.
        assert output_path.exists(), "Should create output file."

        # Parse JSON Lines format.
        with open(output_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]

        # Find the UpliftAssessment record.
        assessment_records = [
            record for record in lines if record.get("_model") == "UpliftAssessment"
        ]
        assert (
            len(assessment_records) == 1
        ), "Should have one `UpliftAssessment` record."

        # Verify the transformed data matches.
        record = assessment_records[0]
        assert record["_model"] == "UpliftAssessment", "Should include `_model` field."
        assert record["id"] == assessment.id, "Should include correct `id`."
        assert record["user_id"] == user.id, "Should include correct `user_id`."
        assert record["user_impact"] == "high", "Should include correct `user_impact`."
        assert (
            record["covered_by_testing"] == "yes"
        ), "Should include correct `covered_by_testing`."
        assert (
            record["risk_associated_with_patch"] == "low"
        ), "Should include correct `risk_associated_with_patch`."
        assert (
            record["created_at"] is not None
        ), "Should include `created_at` as timestamp."
        assert (
            record["updated_at"] is not None
        ), "Should include `updated_at` as timestamp."

    # Should not call BigQuery client methods.
    mock_bq_client.return_value.get_table.assert_not_called()
    mock_bq_client.return_value.insert_rows_json.assert_not_called()
