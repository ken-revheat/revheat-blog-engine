"""Structured JSON logging for the RevHeat Blog Engine."""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "endpoint"):
            log_entry["endpoint"] = record.endpoint
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "response_time"):
            log_entry["response_time"] = record.response_time
        return json.dumps(log_entry)


def setup_logging(log_dir="logs", level="INFO"):
    """Set up structured JSON logging to file (with rotation) and console."""
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()

    # Avoid adding duplicate handlers if called multiple times
    if root_logger.handlers:
        return root_logger

    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler — human-readable
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    console_handler.setFormatter(console_fmt)

    # File handler — JSON structured with rotation (10 MB max, keep 5 backups)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "revheat.log"),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return root_logger
