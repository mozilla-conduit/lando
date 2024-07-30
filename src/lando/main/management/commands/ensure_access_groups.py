from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from lando.main.config.access_groups import ACCESS_GROUPS_CONFIG
from lando.main.models.access_group import AccessGroup

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ensure all Access Groups from the config exist in the database."

    def handle(self, *args, **options):
        for _group_name, group_data in ACCESS_GROUPS_CONFIG.items():
            AccessGroup.objects.get_or_create(
                permission=group_data["permission"],
                defaults=group_data,
            )
