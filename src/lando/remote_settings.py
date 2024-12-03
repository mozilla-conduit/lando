import os

from lando.main.logging import MozLogFormatter
from lando.settings import *  # noqa: F403

STORAGES = {
    "staticfiles": {
        "BACKEND": "storages.backends.gcloud.GoogleCloudStorage",
    },
}
STATIC_URL = os.getenv("STATIC_URL")
GS_BUCKET_NAME = os.getenv("GS_BUCKET_NAME")
GS_PROJECT_ID = os.getenv("GS_PROJECT_ID")
GS_QUERYSTRING_AUTH = False

COMPRESS_URL = STATIC_URL
COMPRESS_STORAGE = "storages.backends.gcloud.GoogleCloudStorage"
COMPRESS_OFFLINE_MANIFEST_STORAGE = COMPRESS_STORAGE
SENTRY_DSN = os.getenv("SENTRY_DSN")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "formatters": {"mozlog": {"()": MozLogFormatter, "mozlog_logger": "lando"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "mozlog",
        },
        "null": {"class": "logging.NullHandler"},
    },
    "loggers": {
        "celery": {"level": LOG_LEVEL, "handlers": ["console"]},
        "django": {"level": LOG_LEVEL, "handlers": ["console"]},
        "lando": {"level": LOG_LEVEL, "handlers": ["console"]},
        # TODO: for below, see bug 1887030.
        "request.summary": {"level": LOG_LEVEL, "handlers": ["console"]},
    },
    "root": {"handlers": ["null"]},
    "disable_existing_loggers": True,
}
