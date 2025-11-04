import logging
from pathlib import Path
from django.core.management.base import CommandError

from lando.api.legacy.workers.uplift_worker import UpliftWorker
from lando.main.management.commands.start_worker import (
    Command as StartWorkerCommand,
)

logger = logging.getLogger(__name__)

MOZ_PHAB_CONFIG_CONTENT = """
[ui]
no_ansi = False
hyperlinks = False

[vcs]
safe_mode = False

[git]
remote =
command_path =

[hg]
command_path =

[submit]
auto_submit = True
always_blocking = False
warn_untracked = True

[patch]
apply_to = base
create_bookmark = False
create_topic = False
create_branch = True
always_full_stack = False
branch_name_template = phab-D{rev_id}
create_commit = True

[updater]
self_last_check = -1
self_auto_update = False
get_pre_releases = True
arc_last_check =

[error_reporting]
report_to_sentry = True

[telemetry]
enabled = True
""".lstrip()


class Command(StartWorkerCommand):
    help = "Start an uplift worker."
    worker_class = UpliftWorker

    def setup_moz_phab_config(self):
        """Write the moz-phab config file to the user's home directory."""
        dest_config = Path.home() / ".moz-phab-config"

        logger.info(f"Writing moz-phab config to {dest_config}.")
        try:
            dest_config.write_text(MOZ_PHAB_CONFIG_CONTENT, encoding="utf-8")
        except OSError as exc:
            raise CommandError(
                f"Failed to write moz-phab config to {dest_config}: {exc}"
            ) from exc

        logger.info("moz-phab config installed successfully.")

    def handle(self, name: str, **options):
        """Set up moz-phab config before starting the worker."""
        self.setup_moz_phab_config()
        super().handle(name, **options)
