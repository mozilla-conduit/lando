from django.db import models

from lando.main.models.landing_job import LandingJob
from lando.main.scm import SCM_TYPE_CHOICES


class TryJob(LandingJob):
    """Represent a Try job."""

    type = "Try"
