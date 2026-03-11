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


def datetime_to_timestamp(dt: datetime | None) -> int | None:
    """Convert a datetime to a Unix timestamp."""
    if dt is None:
        return None
    return int(dt.timestamp())


def sql_table_id(table: bigquery.Table) -> str:
    """Return a fully-qualified table ID in standard SQL format."""
    return f"{table.project}.{table.dataset_id}.{table.table_id}"


def incoming_table_id(table_id: str) -> str:
    """Return an incoming table ID for the given target table ID."""
    return f"{table_id}_incoming"


class ModelTransformer(ABC):
    """Base class for transforming Django models to BigQuery rows."""

    model: type[Model]

    # The environment variable containing the fully-qualified BigQuery table ID,
    # e.g. "project_id.dataset_id.table_id". The schema of the table this ID
    # points to should match the dict returned by `transform`.
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
        """Transform a model instance for loading."""


class RepoTransformer(ModelTransformer):
    """Transformer for `Repo` model."""

    model = Repo
    table_id_env_var = "BQ_REPOS_TABLE_ID"

    def transform(self, instance: Repo) -> dict[str, Any]:
        """Transform a `Repo` instance for loading."""
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


class UpliftAssessmentTransformer(ModelTransformer):
    """Transformer for `UpliftAssessment` model."""

    model = UpliftAssessment
    table_id_env_var = "BQ_UPLIFT_ASSESSMENTS_TABLE_ID"

    def transform(self, instance: UpliftAssessment) -> dict[str, Any]:
        """Transform an `UpliftAssessment` instance for loading."""
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


class UpliftRevisionTransformer(ModelTransformer):
    """Transformer for `UpliftRevision` model."""

    model = UpliftRevision
    table_id_env_var = "BQ_UPLIFT_REVISIONS_TABLE_ID"

    def transform(self, instance: UpliftRevision) -> dict[str, Any]:
        """Transform an `UpliftRevision` instance for loading."""
        return {
            "id": instance.id,
            "assessment_id": instance.assessment_id,
            "revision_id": instance.revision_id,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class UpliftSubmissionTransformer(ModelTransformer):
    """Transformer for `UpliftSubmission` model."""

    model = UpliftSubmission
    table_id_env_var = "BQ_UPLIFT_SUBMISSIONS_TABLE_ID"

    def transform(self, instance: UpliftSubmission) -> dict[str, Any]:
        """Transform an `UpliftSubmission` instance for loading."""
        return {
            "id": instance.id,
            "requested_by_id": instance.requested_by_id,
            "requested_revision_ids": instance.requested_revision_ids,
            "assessment_id": instance.assessment_id,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


class UpliftJobTransformer(ModelTransformer):
    """Transformer for `UpliftJob` model."""

    model = UpliftJob
    table_id_env_var = "BQ_UPLIFT_JOBS_TABLE_ID"

    def transform(self, instance: UpliftJob) -> dict[str, Any]:
        """Transform an `UpliftJob` instance for loading."""
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


class RevisionUpliftJobTransformer(ModelTransformer):
    """Transformer for `RevisionUpliftJob` model."""

    model = RevisionUpliftJob
    table_id_env_var = "BQ_REVISION_UPLIFT_JOBS_TABLE_ID"

    def transform(self, instance: RevisionUpliftJob) -> dict[str, Any]:
        """Transform a `RevisionUpliftJob` instance for loading."""
        return {
            "id": instance.id,
            "uplift_job_id": instance.uplift_job_id,
            "revision_id": instance.revision_id,
            "index": instance.index,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }


# All available transformers.
TRANSFORMERS = [
    RepoTransformer(),
    UpliftAssessmentTransformer(),
    UpliftRevisionTransformer(),
    UpliftSubmissionTransformer(),
    UpliftJobTransformer(),
    RevisionUpliftJobTransformer(),
]


class Loader(ABC):
    """Base class for data loaders."""

    def __init__(self, stdout: IO[str], stderr: IO[str]):
        self.stdout = stdout
        self.stderr = stderr

    @abstractmethod
    def setup(self, transformers: list[ModelTransformer]) -> None:
        """Called once before processing any transformers."""

    @abstractmethod
    def load(self, transformer: ModelTransformer, queryset: QuerySet) -> int:
        """Load data from queryset. Returns number of rows loaded."""

    @abstractmethod
    def finalize(self) -> None:
        """Called once after all transformers are processed."""


class JsonLinesLoader(Loader):
    """Loader that writes data to a JSON Lines file."""

    def __init__(self, stdout: IO[str], stderr: IO[str], output_path: Path):
        super().__init__(stdout, stderr)

        if output_path.exists():
            raise CommandError(f"Output file already exists: {output_path}")

        self.output_path = output_path

    def setup(self, *args, **kwargs):
        """Create the empty output file."""
        self.output_path.touch()

    def load(self, transformer: ModelTransformer, queryset: QuerySet) -> int:
        """Write transformed records to the JSON Lines output file."""
        with self.output_path.open("a") as output_file:
            for record in queryset.iterator():
                row = transformer.transform(record)
                row["_model"] = transformer.name
                output_file.write(json.dumps(row) + "\n")

        return queryset.count()

    def finalize(self, *args, **kwargs):
        """No-op finalize for `JsonLinesLoader`."""
        pass


class BigQueryLoader(Loader):
    """Loader that exports data to BigQuery using temporary incoming tables."""

    def __init__(self, stdout: IO[str], stderr: IO[str], bq_client: bigquery.Client):
        super().__init__(stdout, stderr)
        self.bq_client = bq_client
        self.target_tables: dict[str, bigquery.Table] = {}
        self.incoming_tables: dict[str, bigquery.Table] = {}

    def setup(self, transformers: list[ModelTransformer]) -> None:
        """Create temporary incoming tables in BigQuery for each transformer."""
        for transformer in transformers:
            target = self.bq_client.get_table(transformer.table_id)
            self.target_tables[transformer.table_id] = target

            # Create an incoming table to hold data before merging (delete existing first).
            incoming_id = incoming_table_id(sql_table_id(target))
            self.bq_client.delete_table(incoming_id, not_found_ok=True)
            incoming = bigquery.Table(incoming_id, schema=target.schema)
            self.incoming_tables[transformer.table_id] = self.bq_client.create_table(
                incoming, exists_ok=False
            )
            self.stdout.write(f"Created incoming table for {transformer.name}.\n")

    def load(
        self, transformer: ModelTransformer, queryset: QuerySet, chunk_size: int = 500
    ) -> int:
        """Transform and insert records into the incoming table in chunks."""
        incoming_table = self.incoming_tables[transformer.table_id]
        table_id = sql_table_id(incoming_table)

        # Transform and insert in chunks to avoid memory issues.
        def transform_iterator() -> Iterator[dict]:
            for record in queryset.iterator():
                yield transformer.transform(record)

        for chunk in chunked(transform_iterator(), chunk_size):
            if not self.insert_with_retry(table_id, chunk):
                self.cleanup_incoming_tables()
                raise CommandError(f"Failed to export {transformer.name}. Aborting.")

        return queryset.count()

    def insert_with_retry(
        self,
        table_id: str,
        rows: list[dict],
        max_retries: int = 3,
        retry_base_delay_s: float = 1.0,
    ) -> bool:
        """Insert rows with exponential backoff retry."""
        for attempt in range(max_retries):
            errors = self.bq_client.insert_rows_json(table_id, rows)
            if not errors:
                return True

            if attempt < max_retries - 1:
                delay = retry_base_delay_s * (2**attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} for {table_id} "
                    f"after {delay}s: {errors}"
                )
                time.sleep(delay)

        logger.error(f"Failed to insert to {table_id} after {max_retries} attempts.")
        return False

    def cleanup_incoming_tables(self) -> None:
        """Delete all incoming tables on failure."""
        for incoming_table in self.incoming_tables.values():
            incoming_id = sql_table_id(incoming_table)
            self.bq_client.delete_table(incoming_id, not_found_ok=True)

    def finalize(self) -> None:
        """Merge each incoming table into its target table and clean up."""
        if not self.incoming_tables:
            return

        self.stdout.write("\nMerging incoming tables into target tables...\n")

        for table_id, incoming_table in self.incoming_tables.items():
            incoming_id = sql_table_id(incoming_table)
            target_table = self.target_tables[table_id]

            # Merge incoming data into the target table.
            target_id = sql_table_id(target_table)
            # De-duplicate the incoming table before merging, keeping only
            # the entry with the latest `updated_at` timestamp for each `id`.
            merge_query = f"""
                MERGE `{target_id}` as T
                USING (
                  SELECT *
                  FROM `{incoming_id}`
                  QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY id ORDER BY updated_at DESC
                  ) = 1
                ) as S
                ON T.id = S.id
                WHEN MATCHED THEN
                  UPDATE SET {", ".join(f"{f.name} = S.{f.name}" for f in target_table.schema)}
                WHEN NOT MATCHED THEN
                  INSERT ({", ".join(f.name for f in target_table.schema)})
                  VALUES ({", ".join(f"S.{f.name}" for f in target_table.schema)});
            """
            job = self.bq_client.query(merge_query)
            job.result()

            # Delete the incoming table after merging.
            self.bq_client.delete_table(incoming_id)
            self.stdout.write(f"Merged and cleaned up {incoming_table.table_id}.\n")


def get_last_run_timestamp(bq_client: bigquery.Client, table_id: str) -> datetime:
    """Get the timestamp of the most recently modified entry in BigQuery.

    Returns `datetime.min` (UTC) if no data exists in the table.
    """
    query = f"SELECT MAX(updated_at) as last_run FROM `{table_id}`"

    job = bq_client.query(query)
    rows = list(job.result())

    if len(rows) != 1:
        raise ValueError(
            f"Expected 1 row from `{table_id}` timestamp query, "
            f"got {len(rows)}: {rows}"
        )

    last_run = rows[0].last_run
    if last_run is None:
        return datetime.min.replace(tzinfo=timezone.utc)

    return datetime.fromtimestamp(last_run, tz=timezone.utc)


def parse_since_timestamp(value: str) -> datetime:
    """Parse a `--since` timestamp string, ensuring it is timezone-aware (UTC)."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_cutoff_timestamp(
    bq_client: bigquery.Client,
    full_export: bool,
    since_arg: datetime | None,
) -> datetime:
    """Determine the cutoff timestamp for the export.

    Returns `datetime.min` (UTC) when all records should be exported.
    """
    if full_export:
        return datetime.min.replace(tzinfo=timezone.utc)

    if since_arg:
        return since_arg

    # Query BigQuery for the last run timestamp.
    # Use the UpliftJob table as the reference.
    return get_last_run_timestamp(bq_client, UpliftJobTransformer().table_id)


class Command(BaseCommand):
    help = "Export Lando data to BigQuery for analytics."
    name = "export_to_bigquery"

    def add_arguments(self, parser: CommandParser):
        """Define command-line arguments for the export command."""
        parser.add_argument(
            "--since",
            type=parse_since_timestamp,
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
            missing = [t.table_id_env_var for t in TRANSFORMERS if not t.table_id]
            if missing:
                raise CommandError(f"Missing env vars: {', '.join(missing)}")

        total_start = time.perf_counter()
        bq_client = bigquery.Client()

        # Determine cutoff timestamp.
        since_timestamp = get_cutoff_timestamp(bq_client, full_export, since_arg)
        if since_timestamp == datetime.min.replace(tzinfo=timezone.utc):
            self.stdout.write(
                "No previous export found, starting from the beginning.\n"
            )
        else:
            self.stdout.write(f"Exporting records modified since {since_timestamp}.\n")

        # Select loader.
        if output_file:
            logger.info("Loading into a JSON-lines file.")
            loader = JsonLinesLoader(self.stdout, self.stderr, output_file)
        else:
            logger.info("Loading into BigQuery.")
            loader = BigQueryLoader(self.stdout, self.stderr, bq_client)

        loader.setup(TRANSFORMERS)

        # Process each transformer.
        for transformer in TRANSFORMERS:
            self.stdout.write(f"\nProcessing {transformer.name}...\n")

            queryset = transformer.model.objects.filter(
                Q(created_at__gt=since_timestamp) | Q(updated_at__gt=since_timestamp)
            )

            count = loader.load(transformer, queryset)
            self.stdout.write(f"Loaded {count} rows.\n")

        loader.finalize()

        total_time = round(time.perf_counter() - total_start, 2)
        self.stdout.write(self.style.SUCCESS(f"\nExport completed in {total_time}s."))
