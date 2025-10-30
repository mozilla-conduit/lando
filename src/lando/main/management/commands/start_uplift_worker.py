import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import CommandError

from lando.api.legacy.workers.uplift_worker import UpliftWorker
from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)

logger = logging.getLogger(__name__)


class Command(StartWorkerCommand):
    help = "Start an uplift worker."
    worker_class = UpliftWorker

    def setup_moz_phab_config(self):
        """Copy the moz-phab config file to the user's home directory."""
        source_config = (
            settings.BASE_DIR / "src/api/legacy/workers/config/moz-phab-config"
        )

        home_dir = Path.home()
        dest_config = home_dir / ".moz-phab-config"

        if not source_config.exists():
            raise CommandError(
                f"moz-phab config file not found at {source_config}. "
                "The uplift worker requires this configuration file."
            )

        logger.info(f"Setting up moz-phab config: {source_config} -> {dest_config}.")
        shutil.copy2(source_config, dest_config)
        logger.info("moz-phab config installed successfully.")

    def handle(self, name: str, **options):
        """Set up moz-phab config before starting the worker."""
        self.setup_moz_phab_config()
        super().handle(name, **options)
