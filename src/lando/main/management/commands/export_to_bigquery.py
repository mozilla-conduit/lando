"""Management command to export Lando data to BigQuery for analytics."""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import IO, Any, Iterator

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Model, Q, QuerySet
from google.cloud import bigquery
from more_itertools import chunked

from lando.main.models import BaseModel
from lando.main.models.repo import Repo
from lando.main.models.uplift import (
    RevisionUpliftJob,
    UpliftAssessment,
    UpliftJob,
    UpliftRevision,
    UpliftSubmission,
)

logger = logging.getLogger(__name__)

# Chunk size for BigQuery inserts.
BQ_CHUNK_SIZE = 500

# Retry configuration for BigQuery inserts.
BQ_MAX_RETRIES = 3
BQ_RETRY_BASE_DELAY = 1.0  # seconds


def datetime_to_timestamp(dt: datetime | None) -> int | None:
    """Convert a datetime to a Unix timestamp."""
    if dt is None:
        return None
    return int(dt.timestamp())


def sql_table_id(table: bigquery.Table) -> str:
    """Return a fully-qualified table ID in standard SQL format."""
    return f"{table.project}.{table.dataset_id}.{table.table_id}"


def staging_table_id(table_id: str) -> str:
    """Return a staging table ID for the given table ID."""
    return f"{table_id}_staging"


class Exporter(ABC):
    """Base class for BigQuery exporters."""

    model: type[Model]
    table_id_env_var: str

    @property
    def name(self) -> str:
        """Return the model class name."""
        return self.model.__name__

    @cached_property
    def table_id(self) -> str:
        """Return the BigQuery table ID from environment variable."""
        return os.getenv(self.table_id_env_var, "")

    @abstractmethod
    def transform(self, instance: BaseModel) -> dict[str, Any]:
        """Transform a model instance to a BigQuery row."""


class RepoExporter(Exporter):
    """Exporter for Repo model."""

    model = Repo
    table_id_env_var = "BQ_REPOS_TABLE_ID"

    def transform(self, instance: Repo) -> dict[str, Any]:
        """Transform a `Repo` instance to a BigQuery row."""
        return {
            "id": instance.id,
            "name": instance.name,
            "short_name": instance.short_name,
            "url": instance.url,
            "scm_type": instance.scm_type,
            "is_phabricator_repo": instance.is_phabricator_repo,
            "is_try": instance.is_try,
            "automation_enabled": instance.automation_enabled,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class UpliftAssessmentExporter(Exporter):
    """Exporter for UpliftAssessment model."""

    model = UpliftAssessment
    table_id_env_var = "BQ_UPLIFT_ASSESSMENTS_TABLE_ID"

    def transform(self, instance: UpliftAssessment) -> dict[str, Any]:
        """Transform an `UpliftAssessment` instance to a BigQuery row."""
        return {
            "id": instance.id,
            "user_id": instance.user_id,
            "user_impact": instance.user_impact,
            "covered_by_testing": instance.covered_by_testing,
            "fix_verified_in_nightly": instance.fix_verified_in_nightly,
            "needs_manual_qe_testing": instance.needs_manual_qe_testing,
            "qe_testing_reproduction_steps": instance.qe_testing_reproduction_steps,
            "risk_associated_with_patch": instance.risk_associated_with_patch,
            "risk_level_explanation": instance.risk_level_explanation,
            "string_changes": instance.string_changes,
            "is_android_affected": instance.is_android_affected,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class UpliftRevisionExporter(Exporter):
    """Exporter for UpliftRevision model."""

    model = UpliftRevision
    table_id_env_var = "BQ_UPLIFT_REVISIONS_TABLE_ID"

    def transform(self, instance: UpliftRevision) -> dict[str, Any]:
        """Transform an `UpliftRevision` instance to a BigQuery row."""
        return {
            "id": instance.id,
            "assessment_id": instance.assessment_id,
            "revision_id": instance.revision_id,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class UpliftSubmissionExporter(Exporter):
    """Exporter for UpliftSubmission model."""

    model = UpliftSubmission
    table_id_env_var = "BQ_UPLIFT_SUBMISSIONS_TABLE_ID"

    def transform(self, instance: UpliftSubmission) -> dict[str, Any]:
        """Transform an `UpliftSubmission` instance to a BigQuery row."""
        return {
            "id": instance.id,
            "requested_by_id": instance.requested_by_id,
            "requested_revision_ids": instance.requested_revision_ids,
            "assessment_id": instance.assessment_id,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class UpliftJobExporter(Exporter):
    """Exporter for UpliftJob model."""

    model = UpliftJob
    table_id_env_var = "BQ_UPLIFT_JOBS_TABLE_ID"

    def transform(self, instance: UpliftJob) -> dict[str, Any]:
        """Transform an `UpliftJob` instance to a BigQuery row."""
        return {
            "id": instance.id,
            "status": instance.status,
            "error": instance.error,
            "error_breakdown": instance.error_breakdown,
            "landed_commit_id": instance.landed_commit_id,
            "requester_email": instance.requester_email,
            "attempts": instance.attempts,
            "priority": instance.priority,
            "duration_seconds": instance.duration_seconds,
            "target_repo_id": instance.target_repo_id,
            "created_revision_ids": instance.created_revision_ids,
            "submission_id": instance.submission_id,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class RevisionUpliftJobExporter(Exporter):
    """Exporter for RevisionUpliftJob model."""

    model = RevisionUpliftJob
    table_id_env_var = "BQ_REVISION_UPLIFT_JOBS_TABLE_ID"

    def transform(self, instance: RevisionUpliftJob) -> dict[str, Any]:
        """Transform a `RevisionUpliftJob` instance to a BigQuery row."""
        return {
            "id": instance.id,
            "uplift_job_id": instance.uplift_job_id,
            "revision_id": instance.revision_id,
            "index": instance.index,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


# All available exporters.
EXPORTERS = [
    RepoExporter(),
    UpliftAssessmentExporter(),
    UpliftRevisionExporter(),
    UpliftSubmissionExporter(),
    UpliftJobExporter(),
    RevisionUpliftJobExporter(),
]


class Loader(ABC):
    """Base class for data loaders."""

    def __init__(self, stdout: IO[str], stderr: IO[str]):
        self.stdout = stdout
        self.stderr = stderr

    @abstractmethod
    def setup(self, exporters: list[Exporter]) -> None:
        """Called once before processing any exporters."""

    @abstractmethod
    def load(self, exporter: Exporter, queryset: QuerySet) -> int:
        """Load data from queryset. Returns number of rows loaded."""

    @abstractmethod
    def finalize(self) -> None:
        """Called once after all exporters are processed."""


class JsonLinesLoader(Loader):
    """Loader that writes data to a JSON Lines file."""

    def __init__(self, stdout: IO[str], stderr: IO[str], output_path: Path):
        super().__init__(stdout, stderr)
        self.output_path = output_path
        self.first_write = True

    def setup(self, *args, **kwargs):
        """No-op setup for `JsonLinesLoader`."""
        pass

    def load(self, exporter: Exporter, queryset: QuerySet) -> int:
        """Write transformed records to the JSON Lines output file."""
        mode = "w" if self.first_write else "a"
        self.first_write = False

        with self.output_path.open(mode) as f:
            for record in queryset.iterator():
                row = exporter.transform(record)
                row["_model"] = exporter.name
                f.write(json.dumps(row) + "\n")

        return queryset.count()

    def finalize(self, *args, **kwargs):
        """No-op finalize for `JsonLinesLoader`."""
        pass


class BigQueryLoader(Loader):
    """Loader that exports data to BigQuery using staging tables."""

    def __init__(self, stdout: IO[str], stderr: IO[str], bq_client: bigquery.Client):
        super().__init__(stdout, stderr)
        self.bq_client = bq_client
        self.target_tables: dict[str, bigquery.Table] = {}
        self.staging_tables: dict[str, bigquery.Table] = {}

    def setup(self, exporters: list[Exporter]) -> None:
        """Create staging tables in BigQuery for each exporter."""
        for exporter in exporters:
            target = self.bq_client.get_table(exporter.table_id)
            self.target_tables[exporter.table_id] = target

            # Create staging table (delete existing first).
            staging_id = staging_table_id(sql_table_id(target))
            self.bq_client.delete_table(staging_id, not_found_ok=True)
            staging = bigquery.Table(staging_id, schema=target.schema)
            self.staging_tables[exporter.table_id] = self.bq_client.create_table(
                staging, exists_ok=False
            )
            self.stdout.write(f"Created staging table for {exporter.name}.\n")

    def load(self, exporter: Exporter, queryset: QuerySet) -> int:
        """Transform and insert records into the staging table in chunks."""
        staging_table = self.staging_tables[exporter.table_id]
        table_id = sql_table_id(staging_table)

        # Transform and insert in chunks to avoid memory issues.
        def transform_iterator() -> Iterator[dict]:
            for record in queryset.iterator():
                yield exporter.transform(record)

        for chunk in chunked(transform_iterator(), BQ_CHUNK_SIZE):
            if not self.insert_with_retry(table_id, chunk):
                self.cleanup_staging_tables()
                raise CommandError(f"Failed to export {exporter.name}. Aborting.")

        return queryset.count()

    def finalize(self) -> None:
        """Merge each staging table into its target table and clean up."""
        if not self.staging_tables:
            return

        self.stdout.write("\nMerging staging tables into target tables...\n")

        for table_id, staging_table in self.staging_tables.items():
            staging_id = sql_table_id(staging_table)
            target_table = self.target_tables[table_id]

            # Merge staging into target.
            target_id = sql_table_id(target_table)
            merge_query = f"""
                MERGE `{target_id}` as T
                USING `{staging_id}` as S
                ON T.id = S.id
                WHEN MATCHED THEN
                  UPDATE SET {", ".join(f"{f.name} = S.{f.name}" for f in target_table.schema)}
                WHEN NOT MATCHED THEN
                  INSERT ({", ".join(f.name for f in target_table.schema)})
                  VALUES ({", ".join(f"S.{f.name}" for f in target_table.schema)});
            """
            job = self.bq_client.query(merge_query)
            job.result()

            # Delete staging table.
            self.bq_client.delete_table(staging_id)
            self.stdout.write(f"  Merged and cleaned up {staging_table.table_id}.\n")

    def insert_with_retry(self, table_id: str, rows: list[dict]) -> bool:
        """Insert rows with exponential backoff retry."""
        for attempt in range(BQ_MAX_RETRIES):
            errors = self.bq_client.insert_rows_json(table_id, rows)
            if not errors:
                return True

            if attempt < BQ_MAX_RETRIES - 1:
                delay = BQ_RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{BQ_MAX_RETRIES} for {table_id} "
                    f"after {delay}s: {errors}"
                )
                time.sleep(delay)

        logger.error(f"Failed to insert to {table_id} after {BQ_MAX_RETRIES} attempts.")
        return False

    def cleanup_staging_tables(self) -> None:
        """Delete all staging tables on failure."""
        for staging_table in self.staging_tables.values():
            staging_id = sql_table_id(staging_table)
            self.bq_client.delete_table(staging_id, not_found_ok=True)


def get_last_run_timestamp(
    bq_client: bigquery.Client, table_id: str
) -> datetime | None:
    """Get the timestamp of the most recently modified entry in BigQuery."""
    query = f"SELECT MAX(updated_at) as last_run FROM `{table_id}`"

    job = bq_client.query(query)
    rows = list(job.result())

    if len(rows) != 1:
        raise ValueError("Only one row should be returned by timestamp query.")

    last_run = rows[0].last_run
    if last_run is None:
        return None

    return datetime.fromtimestamp(last_run, tz=timezone.utc)


def get_cutoff_timestamp(
    bq_client: bigquery.Client,
    full_export: bool,
    since_arg: str | None,
) -> datetime | None:
    """Determine the cutoff timestamp for the export."""
    if full_export:
        return None

    if since_arg:
        since_timestamp = datetime.fromisoformat(since_arg)
        if since_timestamp.tzinfo is None:
            since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)
        return since_timestamp

    # Query BigQuery for the last run timestamp.
    # Use the UpliftJob table as the reference.
    return get_last_run_timestamp(bq_client, UpliftJobExporter().table_id)


class Command(BaseCommand):
    help = "Export Lando data to BigQuery for analytics."
    name = "export_to_bigquery"

    def add_arguments(self, parser: CommandParser):
        """Define command-line arguments for the export command."""
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help=(
                "Export records modified since this timestamp (ISO format). "
                "If not specified, queries BigQuery for the last run timestamp."
            ),
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Export all records from the beginning of history.",
        )
        parser.add_argument(
            "--output-file",
            type=Path,
            default=None,
            help="Write transformed data to a JSON file instead of BigQuery.",
        )

    def handle(self, *args, **options):
        """Run the BigQuery export pipeline."""
        full_export = options["full"]
        since_arg = options["since"]
        output_file = options["output_file"]

        # Validate environment variables for BigQuery mode.
        if not output_file:
            missing = [e.table_id_env_var for e in EXPORTERS if not e.table_id]
            if missing:
                raise CommandError(f"Missing env vars: {', '.join(missing)}")

        total_start = time.perf_counter()
        bq_client = bigquery.Client()

        # Determine cutoff timestamp.
        since_timestamp = get_cutoff_timestamp(bq_client, full_export, since_arg)
        if since_timestamp:
            self.stdout.write(f"Exporting records modified since {since_timestamp}.\n")
        else:
            self.stdout.write("Starting full export.\n")

        # Select loader.
        if output_file:
            logger.info("Loading into a JSON-lines file.")
            loader = JsonLinesLoader(self.stdout, self.stderr, output_file)
        else:
            logger.info("Loading into BigQuery.")
            loader = BigQueryLoader(self.stdout, self.stderr, bq_client)

        loader.setup(EXPORTERS)

        # Process each exporter.
        for exporter in EXPORTERS:
            self.stdout.write(f"\nProcessing {exporter.name}...\n")

            queryset = exporter.model.objects.all()
            if since_timestamp:
                queryset = queryset.filter(
                    Q(created_at__gt=since_timestamp)
                    | Q(updated_at__gt=since_timestamp)
                )

            count = loader.load(exporter, queryset)
            self.stdout.write(f"  Loaded {count} rows.\n")

        loader.finalize()

        total_time = round(time.perf_counter() - total_start, 2)
        self.stdout.write(self.style.SUCCESS(f"\nExport completed in {total_time}s."))
