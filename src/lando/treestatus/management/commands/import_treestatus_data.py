import argparse
import logging

import requests
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from lando.treestatus.models import (
    Log,
    Tree,
    TreeCategory,
    TreeStatus,
)

logger = logging.getLogger(__name__)

# Default source instance: the Treestatus service hosted by old-Lando.
DEFAULT_BASE_URL = "https://treestatus.prod.lando.prod.cloudops.mozgcp.net/"


class Command(BaseCommand):
    help = (
        "Import Treestatus data (trees and logs) from another Treestatus instance. "
        "Every local log entry is replaced by the source's, so this command is only "
        "usable while the source instance remains the source of truth: after the "
        "cutover it would discard changes made in Lando."
    )
    name = "import_treestatus_data"

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "base_url",
            nargs="?",
            default=DEFAULT_BASE_URL,
            help=(
                "Base URL of the source Treestatus instance to import from. "
                f"Defaults to old-Lando at `{DEFAULT_BASE_URL}`."
            ),
        )

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/")

        logger.debug(f"Fetching trees from {base_url}.")
        trees_response = requests.get(f"{base_url}/trees")
        trees_response.raise_for_status()
        trees_data = trees_response.json()["result"]

        if not trees_data:
            raise CommandError(f"No trees returned from {base_url}.")

        # Import in a single transaction so a failed run leaves the existing data
        # untouched instead of a half-imported database.
        with transaction.atomic():
            self.delete_logs()

            for tree_info in trees_data.values():
                self.import_tree(tree_info)
                self.import_logs(base_url, tree_info["tree"])

            self.reset_log_id_sequence()

        self.stdout.write(self.style.SUCCESS("Finished importing Treestatus data."))

    def delete_logs(self):
        """Drop every local log entry so the import is a fresh copy of the source.

        Re-running the command is a full re-import rather than a merge: any log
        created locally since the last run is dropped, which keeps the local ids
        aligned with the source's and avoids reconciling diverged rows.
        """
        logger.debug("Deleting existing logs.")
        deleted, _ = Log.objects.all().delete()
        if deleted:
            self.stdout.write(f"Deleted {deleted} existing log(s).")

    def import_tree(self, tree_info: dict):
        """Create a single tree, or re-sync an existing one with the source."""
        tree_name = tree_info["tree"]
        tree, created = Tree.objects.update_or_create(
            tree=tree_name,
            defaults={
                "status": TreeStatus(tree_info["status"]),
                "reason": tree_info["reason"],
                "message_of_the_day": tree_info["message_of_the_day"],
                "category": TreeCategory(tree_info["category"]),
            },
        )
        action = "Created" if created else "Updated"
        self.stdout.write(f"{action} tree {tree.tree}.")

    def import_logs(self, base_url: str, tree_name: str):
        """Recreate the source's log entries for a tree under their original ids.

        Log ids are part of the Treestatus API: they are returned as a tree's
        `log_id` and are what clients pass back to amend a log entry. Reusing the
        source ids keeps those references pointing at the same entry in both
        services, both for API clients and for stack entries recording a
        `log_id`.
        """
        logger.debug(f"Fetching logs for {tree_name}.")
        logs_response = requests.get(f"{base_url}/trees/{tree_name}/logs_all")
        logs_response.raise_for_status()
        log_entries = logs_response.json()["result"]

        logs = [
            Log(
                id=log_entry["id"],
                tree_id=tree_name,
                changed_by=log_entry["who"],
                status=TreeStatus(log_entry["status"]),
                reason=log_entry["reason"],
                tags=log_entry["tags"],
            )
            for log_entry in log_entries
        ]
        Log.objects.bulk_create(logs)

        # `created_at` is `auto_now_add`, so the source's `when` has to be set after
        # insertion. `updated_at` keeps its local meaning of "when this row was last
        # written", which for an imported log is the time of the import.
        for log, log_entry in zip(logs, log_entries, strict=True):
            log.created_at = parse_datetime(log_entry["when"])
        Log.objects.bulk_update(logs, ["created_at"])

        self.stdout.write(f"Imported {len(logs)} log(s) for {tree_name}.")

    def reset_log_id_sequence(self):
        """Advance the `Log` id sequence past the imported primary keys.

        Logs are inserted with their source ids, which leaves the sequence
        untouched, so without this the next non-imported insert would collide
        with an imported row.
        """
        logger.debug("Resetting the `Log` id sequence.")
        reset_statements = connection.ops.sequence_reset_sql(no_style(), [Log])
        with connection.cursor() as cursor:
            for statement in reset_statements:
                cursor.execute(statement)
