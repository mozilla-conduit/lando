import logging
import os

from celery import Celery
from celery.signals import (
    after_task_publish,
    heartbeat_sent,
    setup_logging,
    task_failure,
    task_retry,
    task_success,
)
from datadog import statsd

logger = logging.getLogger(__name__)


# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lando.settings")

app = Celery("lando")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@after_task_publish.connect
def count_task_published(**kwargs):
    # This is published by the app when a new task is kicked off.  It is also
    # published by workers when they put a task back on the queue for retrying.
    statsd.increment("lando-api.celery.tasks_published")


@heartbeat_sent.connect
def count_heartbeat(**kwargs):
    statsd.increment("lando-api.celery.heartbeats_from_workers")


@task_success.connect
def count_task_success(**kwargs):
    statsd.increment("lando-api.celery.tasks_succeeded")


@task_failure.connect
def count_task_failure(**kwargs):
    statsd.increment("lando-api.celery.tasks_failed")


@task_retry.connect
def count_task_retried(**kwargs):
    statsd.increment("lando-api.celery.tasks_retried")


@setup_logging.connect
def setup_celery_logging(**kwargs):
    # Prevent celery from overriding our logging configuration.
    pass
