"""
Pipeline Logger — structured, persistent logging for the dispatch pipeline.

Every stage of fork-and-assign writes structured log entries to a JSONL file
so we can diagnose failures, measure duration, and trace the full execution
path for each dispatch.

Log file: backend/.cache/oss/pipeline.log (JSONL format, one JSON object per line)
"""

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler

from .cache import CACHE_DIR

# --- File-based structured logging ---

_LOG_DIR = os.path.join(CACHE_DIR, "oss")
_LOG_FILE = os.path.join(_LOG_DIR, "pipeline.log")

# Module-level logger for pipeline events
logger = logging.getLogger("pipeline")


def _ensure_log_dir():
    os.makedirs(_LOG_DIR, exist_ok=True)


def setup_pipeline_logging():
    """Configure the pipeline logger with file + console output.

    Call this once at app startup. Safe to call multiple times.
    """
    if logger.handlers:
        return  # already configured

    _ensure_log_dir()
    logger.setLevel(logging.DEBUG)

    # File handler — rotated at 5MB, keep 3 backups
    fh = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    ))
    fh.formatter.converter = time.gmtime
    logger.addHandler(fh)

    # Console handler — INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)


# --- Structured event logging (JSONL) ---

_EVENTS_FILE = os.path.join(_LOG_DIR, "pipeline-events.jsonl")


def log_event(stage, step, slug, issue_number=None, status="ok", detail=None,
              duration_ms=None, extra=None):
    """Write a structured event to the JSONL events file.

    Args:
        stage: Pipeline stage (e.g., "stage3", "stage4")
        step: Step within the stage (e.g., "fork", "sync", "context", "assign")
        slug: Repo slug (e.g., "microsoft/vscode")
        issue_number: Upstream issue number
        status: "ok", "error", "skip", "timeout"
        detail: Human-readable detail string
        duration_ms: How long this step took in milliseconds
        extra: Dict of additional structured data
    """
    _ensure_log_dir()
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": stage,
        "step": step,
        "slug": slug,
        "issue": issue_number,
        "status": status,
        "detail": detail,
    }
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    if extra:
        event.update(extra)

    with open(_EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


class StepTimer:
    """Context manager for timing a pipeline step and logging the result.

    Usage:
        with StepTimer("stage3", "fork", "microsoft/vscode", issue_number=12345):
            svc.fork_repo(owner, repo)
    """

    def __init__(self, stage, step, slug, issue_number=None):
        self.stage = stage
        self.step = step
        self.slug = slug
        self.issue_number = issue_number
        self._start = None
        self.status = "ok"
        self.detail = None
        self.extra = None

    def __enter__(self):
        self._start = time.monotonic()
        logger.debug("[%s] %s — %s #%s starting", self.stage, self.step,
                     self.slug, self.issue_number)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = int((time.monotonic() - self._start) * 1000)
        if exc_type:
            self.status = "error"
            self.detail = f"{exc_type.__name__}: {exc_val}"
        log_event(self.stage, self.step, self.slug, self.issue_number,
                  status=self.status, detail=self.detail,
                  duration_ms=elapsed, extra=self.extra)
        level = logging.WARNING if self.status == "error" else logging.DEBUG
        logger.log(level, "[%s] %s — %s #%s %s (%dms) %s",
                   self.stage, self.step, self.slug, self.issue_number,
                   self.status, elapsed, self.detail or "")
        return False  # don't suppress exceptions
