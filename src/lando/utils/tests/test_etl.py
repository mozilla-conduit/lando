import json
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from lando.utils.management.commands.export_to_bigquery import (
    Command,
    JsonLinesLoader,
    RepoTransformer,
    RevisionUpliftJobTransformer,
    UpliftAssessmentTransformer,
    UpliftJobTransformer,
    UpliftRevisionTransformer,
    UpliftSubmissionTransformer,
    datetime_to_timestamp,
    incoming_table_id,
    parse_since_timestamp,
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

    transformer = RepoTransformer()
    result = transformer.transform(repo)

    assert result["id"] == repo.id, "`id` should exist and match expected value."
    assert result["name"] == "repo-1", "`name` should exist and match expected value."
    assert (
        result["short_name"] == repo.short_name
    ), "`short_name` should exist and match expected value."
    assert result["url"] == repo.url, "`url` should exist and match expected value."
    assert (
        result["scm_type"] == "git"
    ), "`scm_type` should exist and match expected value."
    assert (
        result["is_phabricator_repo"] is True
    ), "`is_phabricator_repo` should exist and match expected value."
    assert result["is_try"] is False, "`is_try` should exist and match expected value."
    assert (
        result["automation_enabled"] is False
    ), "`automation_enabled` should exist and match expected value."
    assert (
        result["created_at"] is not None
    ), "`created_at` should exist and not be `None`."
    assert (
        result["updated_at"] is not None
    ), "`updated_at` should exist and not be `None`."


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

    transformer = UpliftAssessmentTransformer()
    result = transformer.transform(assessment)

    assert result["id"] == assessment.id, "`id` should exist and match expected value."
    assert (
        result["user_id"] == user.id
    ), "`user_id` should exist and match expected value."
    assert (
        result["user_impact"] == "high"
    ), "`user_impact` should exist and match expected value."
    assert (
        result["covered_by_testing"] == "yes"
    ), "`covered_by_testing` should exist and match expected value."
    assert (
        result["fix_verified_in_nightly"] == "no"
    ), "`fix_verified_in_nightly` should exist and match expected value."
    assert (
        result["needs_manual_qe_testing"] == "yes"
    ), "`needs_manual_qe_testing` should exist and match expected value."
    assert (
        result["qe_testing_reproduction_steps"] == "Step 1, Step 2"
    ), "`qe_testing_reproduction_steps` should exist and match expected value."
    assert (
        result["risk_associated_with_patch"] == "low"
    ), "`risk_associated_with_patch` should exist and match expected value."
    assert (
        result["risk_level_explanation"] == "Simple change"
    ), "`risk_level_explanation` should exist and match expected value."
    assert (
        result["string_changes"] == "none"
    ), "`string_changes` should exist and match expected value."
    assert (
        result["is_android_affected"] == "yes"
    ), "`is_android_affected` should exist and match expected value."
    assert (
        result["created_at"] is not None
    ), "`created_at` should exist and not be `None`."
    assert (
        result["updated_at"] is not None
    ), "`updated_at` should exist and not be `None`."


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

    transformer = UpliftRevisionTransformer()
    result = transformer.transform(revision)

    assert result["id"] == revision.id, "`id` should exist and match expected value."
    assert (
        result["assessment_id"] == assessment.id
    ), "`assessment_id` should exist and match expected value."
    assert (
        result["revision_id"] == 12345
    ), "`revision_id` should exist and match expected value."
    assert (
        result["created_at"] is not None
    ), "`created_at` should exist and not be `None`."
    assert (
        result["updated_at"] is not None
    ), "`updated_at` should exist and not be `None`."


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

    transformer = UpliftSubmissionTransformer()
    result = transformer.transform(submission)

    assert result["id"] == submission.id, "`id` should exist and match expected value."
    assert (
        result["requested_by_id"] == user.id
    ), "`requested_by_id` should exist and match expected value."
    assert result["requested_revision_ids"] == [
        100,
        101,
        102,
    ], "`requested_revision_ids` should exist and match expected value."
    assert (
        result["assessment_id"] == assessment.id
    ), "`assessment_id` should exist and match expected value."
    assert (
        result["created_at"] is not None
    ), "`created_at` should exist and not be `None`."
    assert (
        result["updated_at"] is not None
    ), "`updated_at` should exist and not be `None`."


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

    transformer = UpliftJobTransformer()
    result = transformer.transform(job)

    assert result["id"] == job.id, "`id` should exist and match expected value."
    assert (
        result["status"] == "LANDED"
    ), "`status` should exist and match expected value."
    assert result["error"] == "", "`error` should exist and match expected value."
    assert (
        result["error_breakdown"] == {}
    ), "`error_breakdown` should exist and match expected value."
    assert (
        result["landed_commit_id"] == "abc123"
    ), "`landed_commit_id` should exist and match expected value."
    assert (
        result["requester_email"] == "user@example.com"
    ), "`requester_email` should exist and match expected value."
    assert result["attempts"] == 2, "`attempts` should exist and match expected value."
    assert result["priority"] == 1, "`priority` should exist and match expected value."
    assert (
        result["duration_seconds"] == 120
    ), "`duration_seconds` should exist and match expected value."
    assert (
        result["target_repo_id"] == repo.id
    ), "`target_repo_id` should exist and match expected value."
    assert result["created_revision_ids"] == [
        200,
        201,
    ], "`created_revision_ids` should exist and match expected value."
    assert (
        result["submission_id"] == submission.id
    ), "`submission_id` should exist and match expected value."
    assert (
        result["created_at"] is not None
    ), "`created_at` should exist and not be `None`."
    assert (
        result["updated_at"] is not None
    ), "`updated_at` should exist and not be `None`."


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

    transformer = RevisionUpliftJobTransformer()
    result = transformer.transform(revision_uplift_job)

    assert (
        result["id"] == revision_uplift_job.id
    ), "`id` should exist and match expected value."
    assert (
        result["uplift_job_id"] == job.id
    ), "`uplift_job_id` should exist and match expected value."
    assert result["revision_id"] is None, "`revision_id` should exist and be `None`."
    assert result["index"] == 0, "`index` should exist and match expected value."
    assert (
        result["created_at"] is not None
    ), "`created_at` should exist and not be `None`."
    assert (
        result["updated_at"] is not None
    ), "`updated_at` should exist and not be `None`."


def test_get_cutoff_timestamp_full_export_returns_datetime_min():
    command = Command()

    result = command.get_cutoff_timestamp(full_export=True, since=None)

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
def test_parse_since_timestamp(since_arg, expected, msg):
    result = parse_since_timestamp(since_arg)

    assert result == expected, msg


def test_get_cutoff_timestamp_returns_since_when_provided():
    command = Command()
    since = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)

    result = command.get_cutoff_timestamp(full_export=False, since=since)

    assert result == since, "Should return the provided `since` `datetime`."


@pytest.mark.parametrize(
    "bq_return,expected,msg",
    [
        (
            datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc),
            "Should return timestamp from BigQuery.",
        ),
        (
            datetime.min.replace(tzinfo=timezone.utc),
            datetime.min.replace(tzinfo=timezone.utc),
            "Should return `datetime.min` (UTC) when BigQuery has no previous data.",
        ),
    ],
)
@patch("lando.utils.management.commands.export_to_bigquery.get_last_run_timestamp")
@patch("lando.utils.management.commands.export_to_bigquery.bigquery.Client")
def test_get_cutoff_timestamp_falls_back_to_bigquery(
    mock_bq_client, mock_get_last_run, bq_return, expected, msg
):
    command = Command()
    mock_get_last_run.return_value = bq_return

    result = command.get_cutoff_timestamp(full_export=False, since=None)

    assert result == expected, msg


@patch("lando.utils.management.commands.export_to_bigquery.bigquery.Client")
def test_get_cutoff_timestamp_falls_back_to_beginning_on_bq_error(mock_bq_client):
    mock_bq_client.side_effect = Exception("Could not connect.")
    command = Command()

    result = command.get_cutoff_timestamp(full_export=False, since=None)

    assert result == datetime.min.replace(
        tzinfo=timezone.utc
    ), "Should fall back to `datetime.min` (UTC) when BigQuery is unavailable."


def test_json_lines_loader_raises_if_output_file_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "export.jsonl"
        output_path.touch()

        with pytest.raises(CommandError, match="Output file already exists"):
            JsonLinesLoader(StringIO(), StringIO(), output_path)


@pytest.mark.django_db
@patch("lando.utils.management.commands.export_to_bigquery.bigquery.Client")
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
        assert (
            record["_model"] == "UpliftAssessment"
        ), "`_model` should exist and match expected value."
        assert (
            record["id"] == assessment.id
        ), "`id` should exist and match expected value."
        assert (
            record["user_id"] == user.id
        ), "`user_id` should exist and match expected value."
        assert (
            record["user_impact"] == "high"
        ), "`user_impact` should exist and match expected value."
        assert (
            record["covered_by_testing"] == "yes"
        ), "`covered_by_testing` should exist and match expected value."
        assert (
            record["risk_associated_with_patch"] == "low"
        ), "`risk_associated_with_patch` should exist and match expected value."
        assert (
            record["created_at"] is not None
        ), "`created_at` should exist and not be `None`."
        assert (
            record["updated_at"] is not None
        ), "`updated_at` should exist and not be `None`."

    # Should not call BigQuery client methods.
    mock_bq_client.return_value.get_table.assert_not_called()
    mock_bq_client.return_value.insert_rows_json.assert_not_called()
