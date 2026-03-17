"""Management command to ETL Lando data into BigQuery for analytics."""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Iterator

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Model, Q, QuerySet
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from google.cloud.bigquery import Table
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


class ModelTransformer:
    """Base class for transforming Django models to BigQuery rows.

    Subclasses declare `model`, `table_id_env_var`, and `fields`. The base
    `transform` method handles `id`, `created_at`, and `updated_at` automatically,
    then copies each field in `fields` from the model instance via `getattr`.

    Override `transform` in a subclass if you need derived fields.
    """

    model: type[Model]

    # The environment variable containing the fully-qualified BigQuery table ID,
    # e.g. "project_id.dataset_id.table_id". The schema of the table this ID
    # points to should match the dict returned by `transform`.
    table_id_env_var: str

    # Model fields to include in the transformed output (beyond the base fields).
    fields: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """Return the model class name."""
        return self.model.__name__

    @cached_property
    def table_id(self) -> str:
        """Return the BigQuery table ID from environment variable."""
        return os.getenv(self.table_id_env_var, "")

    def transform(self, instance: BaseModel) -> dict[str, Any]:
        """Transform a model instance for loading."""
        data = {
            "id": instance.id,
            "created_at": datetime_to_timestamp(instance.created_at),
            "updated_at": datetime_to_timestamp(instance.updated_at),
        }
        for field in self.fields:
            data[field] = getattr(instance, field)
        return data


class RepoTransformer(ModelTransformer):
    """Transformer for `Repo` model."""

    model = Repo
    table_id_env_var = "BQ_REPOSITORIES_TABLE_ID"
    fields = (
        "name",
        "short_name",
        "url",
        "scm_type",
        "is_phabricator_repo",
        "is_try",
        "automation_enabled",
    )


class UpliftAssessmentTransformer(ModelTransformer):
    """Transformer for `UpliftAssessment` model."""

    model = UpliftAssessment
    table_id_env_var = "BQ_UPLIFT_ASSESSMENTS_TABLE_ID"
    fields = (
        "user_id",
        "user_impact",
        "covered_by_testing",
        "fix_verified_in_nightly",
        "needs_manual_qe_testing",
        "qe_testing_reproduction_steps",
        "risk_associated_with_patch",
        "risk_level_explanation",
        "string_changes",
        "is_android_affected",
    )


class UpliftRevisionTransformer(ModelTransformer):
    """Transformer for `UpliftRevision` model."""

    model = UpliftRevision
    table_id_env_var = "BQ_UPLIFT_REVISIONS_TABLE_ID"
    fields = (
        "assessment_id",
        "revision_id",
    )


class UpliftSubmissionTransformer(ModelTransformer):
    """Transformer for `UpliftSubmission` model."""

    model = UpliftSubmission
    table_id_env_var = "BQ_UPLIFT_SUBMISSIONS_TABLE_ID"
    fields = (
        "requested_by_id",
        "requested_revision_ids",
        "assessment_id",
    )


class UpliftJobTransformer(ModelTransformer):
    """Transformer for `UpliftJob` model."""

    model = UpliftJob
    table_id_env_var = "BQ_UPLIFT_JOBS_TABLE_ID"
    fields = (
        "status",
        "error",
        "landed_commit_id",
        "requester_email",
        "attempts",
        "priority",
        "duration_seconds",
        "target_repo_id",
        "created_revision_ids",
        "submission_id",
    )

    def transform(self, instance: BaseModel) -> dict[str, Any]:
        """Transform an `UpliftJob` instance for loading.

        The `error_breakdown` field is a `JSONField` which returns a Python
        dict, but BigQuery's `JSON` column type expects a JSON string when
        using the streaming insert API.
        """
        data = super().transform(instance)
        data["error_breakdown"] = json.dumps(instance.error_breakdown)
        return data


class RevisionUpliftJobTransformer(ModelTransformer):
    """Transformer for `RevisionUpliftJob` model."""

    model = RevisionUpliftJob
    table_id_env_var = "BQ_REVISION_UPLIFT_JOBS_TABLE_ID"
    fields = (
        "uplift_job_id",
        "revision_id",
        "index",
    )


# All available transformers.
TRANSFORMERS = [
    RepoTransformer(),
    UpliftAssessmentTransformer(),
    UpliftRevisionTransformer(),
    UpliftSubmissionTransformer(),
    UpliftJobTransformer(),
    RevisionUpliftJobTransformer(),
]


def extract(model: type[Model], since: datetime) -> QuerySet:
    """Return records created or updated after `since`."""
    return model.objects.filter(Q(created_at__gt=since) | Q(updated_at__gt=since))


class Loader(ABC):
    """Base class for data loaders."""

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

    def __init__(self, output_path: Path):
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
    """Loader that loads data into BigQuery using temporary incoming tables."""

    def __init__(self, bq_client: bigquery.Client):
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
            logger.info("Created incoming table for %s.", transformer.name)

        self.wait_for_incoming_tables()

    def wait_for_incoming_tables(
        self, max_retries: int = 5, retry_base_delay_s: float = 1.0
    ) -> None:
        """Wait for all incoming tables to be visible to the BigQuery API.

        BigQuery's streaming insert API is eventually consistent with table
        creation, so a newly created table may not be immediately available.
        This method polls `get_table` for each incoming table until all are
        confirmed visible, preventing `NotFound` errors on the first insert.
        """
        pending: list[Table] = list(self.incoming_tables.values())

        for attempt in range(max_retries):
            still_pending: list[Table] = []
            for table in pending:
                try:
                    self.bq_client.get_table(sql_table_id(table))
                except NotFound:
                    still_pending.append(table)

            if not still_pending:
                logger.debug("All incoming tables are ready.")
                return

            delay = retry_base_delay_s * (2**attempt)
            logger.warning(
                "Waiting %.1fs for %d incoming table(s) to become visible.",
                delay,
                len(still_pending),
            )
            time.sleep(delay)
            pending = still_pending

        table_ids = [sql_table_id(table) for table in pending]
        self.cleanup_incoming_tables()
        raise CommandError(
            f"Incoming tables not visible after {max_retries} retries: "
            f"{', '.join(table_ids)}"
        )

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
                raise CommandError(f"Failed to load {transformer.name}. Aborting.")

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

        logger.info("Merging incoming tables into target tables.")

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
            logger.info("Merged and cleaned up %s.", incoming_table.table_id)


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


class Command(BaseCommand):
    help = "ETL Lando data into BigQuery for analytics."
    name = "etl"

    def add_arguments(self, parser: CommandParser):
        """Define command-line arguments for the ETL command."""
        parser.add_argument(
            "--since",
            type=parse_since_timestamp,
            default=None,
            help=(
                "Extract records modified since this timestamp (ISO format). "
                "If not specified, queries BigQuery for the last run timestamp."
            ),
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Extract all records from the beginning of history.",
        )
        parser.add_argument(
            "--output-file",
            type=Path,
            default=None,
            help="Write transformed data to a JSON file instead of BigQuery.",
        )

    def get_cutoff_timestamp(
        self,
        full_extract: bool,
        since: datetime | None,
    ) -> datetime:
        """Determine the cutoff timestamp for extraction.

        Checks `--full` first, then `--since`, then falls back to querying
        BigQuery for the last run timestamp.
        """
        if full_extract:
            logger.info("Full extraction requested, starting from the beginning.")
            return datetime.min.replace(tzinfo=timezone.utc)

        if since:
            logger.info("Extracting records modified since %s.", since)
            return since

        # Query BigQuery for the last run timestamp.
        # Use the UpliftJob table as the reference.
        try:
            bq_client = bigquery.Client()
            last_run = get_last_run_timestamp(
                bq_client, UpliftJobTransformer().table_id
            )
        except Exception:
            logger.warning(
                "Could not query BigQuery for last run timestamp. "
                "Starting from the beginning."
            )
            return datetime.min.replace(tzinfo=timezone.utc)

        if last_run == datetime.min.replace(tzinfo=timezone.utc):
            logger.info("No previous ETL run found, starting from the beginning.")
        else:
            logger.info("Extracting records modified since %s.", last_run)

        return last_run

    def handle(self, *args, **options):
        """Run the ETL pipeline."""
        output_file = options["output_file"]

        # Validate environment variables for BigQuery mode.
        if not output_file:
            missing = [t.table_id_env_var for t in TRANSFORMERS if not t.table_id]
            if missing:
                raise CommandError(f"Missing env vars: {', '.join(missing)}")

        total_start = time.perf_counter()

        since_timestamp = self.get_cutoff_timestamp(options["full"], options["since"])

        # Select loader.
        if output_file:
            logger.info("Loading into a JSON-lines file.")
            loader = JsonLinesLoader(output_file)
        else:
            logger.info("Loading into BigQuery.")
            loader = BigQueryLoader(bigquery.Client())

        loader.setup(TRANSFORMERS)

        # Process each transformer.
        for transformer in TRANSFORMERS:
            logger.info("Processing %s.", transformer.name)

            queryset = extract(transformer.model, since_timestamp)

            count = loader.load(transformer, queryset)
            logger.info("Loaded %d rows.", count)

        loader.finalize()

        total_time = round(time.perf_counter() - total_start, 2)
        logger.info("ETL completed in %ss.", total_time)
