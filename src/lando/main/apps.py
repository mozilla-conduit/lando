from django.apps import AppConfig
from django.db.models.signals import post_save

from lando.main.sentry import init_sentry


class MainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lando.main"

    def ready(self):
        """Run initialization tasks."""
        init_sentry()
        self._connect_job_signals()

    def _connect_job_signals(self):
        """Connect post_save signal to all concrete BaseJob subclasses."""
        # Models can't be imported until after Apps have been loaded. This
        # file is imported during that loading process. If we try to import
        # these at the top level of the file we end up with:
        # django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet.
        from lando.headless_api.models.automation_job import AutomationJob
        from lando.main.models.jobs import emit_creation_metric
        from lando.main.models.landing_job import LandingJob
        from lando.main.models.uplift import UpliftJob

        for job_model in [LandingJob, AutomationJob, UpliftJob]:
            post_save.connect(emit_creation_metric, sender=job_model)
