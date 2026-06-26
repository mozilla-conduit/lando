import argparse
import logging

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
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
    help = "Import Treestatus data (trees and logs) from another Treestatus instance."
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

        with transaction.atomic():
            for tree_info in trees_data.values():
                self.import_tree(base_url, tree_info)

        self.stdout.write(self.style.SUCCESS("Finished importing Treestatus data."))

    def import_tree(self, base_url: str, tree_info: dict):
        """Import a single tree and its complete log history."""
        tree_name = tree_info["tree"]
        if Tree.objects.filter(tree=tree_name).exists():
            self.stdout.write(
                self.style.WARNING(f"Tree {tree_name} already exists, skipping.")
            )
            return

        self.stdout.write(f"Creating tree {tree_name}.")
        new_tree = Tree.objects.create(
            tree=tree_name,
            status=TreeStatus(tree_info["status"]),
            reason=tree_info["reason"],
            message_of_the_day=tree_info["message_of_the_day"],
            category=TreeCategory(tree_info["category"]),
        )

        logger.debug(f"Fetching logs for {tree_name}.")
        logs_response = requests.get(f"{base_url}/trees/{tree_name}/logs_all")
        logs_response.raise_for_status()
        logs = logs_response.json()["result"]

        # The API returns logs newest-first; reverse so they are recreated in
        # chronological order.
        self.stdout.write(f"Importing {len(logs)} log(s) for {tree_name}.")
        for log_entry in reversed(logs):
            self.import_log(new_tree, log_entry)

    def import_log(self, tree: Tree, log_entry: dict):
        """Create a single `Log` entry, preserving its original timestamp."""
        log = Log.objects.create(
            tree=tree,
            changed_by=log_entry["who"],
            status=TreeStatus(log_entry["status"]),
            reason=log_entry["reason"],
            tags=log_entry["tags"],
        )

        # `created_at`/`updated_at` use `auto_now_add`/`auto_now`, so a queryset
        # update is needed to retain the historical timestamp from the source.
        when = parse_datetime(log_entry["when"])
        Log.objects.filter(pk=log.pk).update(created_at=when, updated_at=when)
