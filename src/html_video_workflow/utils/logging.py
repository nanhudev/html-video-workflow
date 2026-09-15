"""Unified logging: console + per-job log file. No stray print() calls."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from ..config.paths import logs_dir

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
DATE_FORMAT = "%H:%M:%S"

_root_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _root_configured
    if _root_configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root = logging.getLogger("html_video_workflow")
    root.setLevel(level.upper())
    root.addHandler(handler)
    root.propagate = False
    _root_configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"html_video_workflow.{name}" if not name.startswith(
        "html_video_workflow"
    ) else name)


class JobLogHandler(logging.Handler):
    """Mirror records into ``<logs_dir>/<job_id>.log``."""

    def __init__(self, job_id: str, level: int = logging.DEBUG) -> None:
        super().__init__(level=level)
        self.path: Path = logs_dir() / f"{job_id}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - IO
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(self.format(record) + "\n")
        except OSError:
            self.handleError(record)


def attach_job_log(job_id: str, level: str = "DEBUG") -> JobLogHandler:
    configure_logging()
    handler = JobLogHandler(job_id, level=getattr(logging, level.upper(), logging.DEBUG))
    logging.getLogger("html_video_workflow").addHandler(handler)
    return handler


def detach_job_log(handler: JobLogHandler) -> None:
    logging.getLogger("html_video_workflow").removeHandler(handler)
