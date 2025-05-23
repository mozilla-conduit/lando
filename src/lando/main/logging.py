from __future__ import annotations

import json
import logging
import socket
import traceback

logger = logging.getLogger(__name__)


class MozLogFormatter(logging.Formatter):
    """A mozlog logging formatter.

    https://mzl.la/2NhT1E6
    """

    MOZLOG_ENVVERSION = "2.0"

    # Syslog severity levels.
    SL_EMERG = 0  # system is unusable
    SL_ALERT = 1  # action must be taken immediately
    SL_CRIT = 2  # critical conditions
    SL_ERR = 3  # error conditions
    SL_WARNING = 4  # warning conditions
    SL_NOTICE = 5  # normal but significant condition
    SL_INFO = 6  # informational
    SL_DEBUG = 7  # debug-level messages

    # Mapping from python logging priority to Syslog severity level.
    PRIORITY = {
        "DEBUG": SL_DEBUG,
        "INFO": SL_INFO,
        "WARNING": SL_WARNING,
        "ERROR": SL_ERR,
        "CRITICAL": SL_CRIT,
    }

    BUILTIN_LOGRECORD_ATTRIBUTES = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def __init__(self, *args, mozlog_logger: str | None = None, **kwargs):
        self.mozlog_logger = mozlog_logger or "Dockerflow"
        self.hostname = socket.gethostname()
        super().__init__(*args, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        """Formats a log record and serializes to mozlog json"""

        # NOTE: Django passes some fields that are not JSON serializable in the record
        # (for example, the WSGIRequest object representing the request). Therefore
        # those values are converted to a string to avoid any issues when serializing.
        mozlog_record = {
            "EnvVersion": self.MOZLOG_ENVVERSION,
            "Hostname": self.hostname,
            "Logger": self.mozlog_logger,
            "Type": record.name,
            "Timestamp": int(record.created * 1e9),
            "Severity": self.PRIORITY.get(record.levelname, self.SL_WARNING),
            "Pid": record.process,
            "Fields": {
                k: str(v)
                for k, v in record.__dict__.items()
                if k not in self.BUILTIN_LOGRECORD_ATTRIBUTES
            },
        }

        msg = record.getMessage()
        if msg and "msg" not in mozlog_record["Fields"]:
            mozlog_record["Fields"]["msg"] = msg

        if record.exc_info is not None:
            mozlog_record["Fields"]["exc"] = {
                "error": repr(record.exc_info[1]),  # Instance
                "traceback": "".join(traceback.format_tb(record.exc_info[2])),
            }

        return self.serialize(mozlog_record)

    def serialize(self, mozlog_record: dict) -> str:
        """Serialize a mozlog record."""
        return json.dumps(mozlog_record, sort_keys=True)


class PrettyMozLogFormatter(MozLogFormatter):
    """A mozlog logging formatter which pretty prints."""

    def serialize(self, mozlog_record: dict) -> str:
        """Serialize a mozlog record."""
        return json.dumps(mozlog_record, sort_keys=True, indent=2)
