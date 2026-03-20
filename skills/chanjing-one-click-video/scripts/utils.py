"""
Logging, timing, and common utilities.
Sensitive fields (tokens, keys) are masked before logging.
"""

from __future__ import annotations
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("CHANJING_LOG_FILE", "")

_fmt = "[%(asctime)s] %(levelname)s | %(name)s | %(message)s"
_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
if LOG_FILE:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))

logging.basicConfig(level=LOG_LEVEL, format=_fmt, handlers=_handlers)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Sensitive field masking
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {"access_token", "secret_key", "app_secret", "token", "authorization"}


def mask_sensitive(obj: Any, depth: int = 0) -> Any:
    """Recursively mask sensitive string values in dicts."""
    if depth > 8:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***MASKED***" if k.lower() in _SENSITIVE_KEYS else mask_sensitive(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_sensitive(i, depth + 1) for i in obj]
    return obj


def safe_json(obj: Any) -> str:
    return json.dumps(mask_sensitive(obj), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Timing context manager
# ---------------------------------------------------------------------------

@contextmanager
def timed(label: str, logger: logging.Logger | None = None):
    log = logger or get_logger("timer")
    start = time.perf_counter()
    log.info("▶ %s", label)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info("✓ %s  (%.2fs)", label, elapsed)


# ---------------------------------------------------------------------------
# Polling helper
# ---------------------------------------------------------------------------

def poll_until(
    fn,
    is_done,
    interval: float = 3.0,
    timeout: float = 300.0,
    label: str = "task",
    logger: logging.Logger | None = None,
):
    """
    Call fn() repeatedly until is_done(result) is True, then return result.
    Raises TimeoutError if timeout exceeded.
    """
    log = logger or get_logger("poller")
    deadline = time.time() + timeout
    attempt = 0
    while True:
        result = fn()
        if is_done(result):
            return result
        attempt += 1
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"{label} did not complete within {timeout}s")
        sleep_time = min(interval, remaining)
        log.debug("Polling %s (attempt %d, %.0fs remaining)…", label, attempt, remaining)
        time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Output dir helper
# ---------------------------------------------------------------------------

def ensure_output_dir(name: str = "chanjing-one-click-video") -> Path:
    p = Path("outputs") / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_VAGUE_INPUTS = {"你好", "hello", "随便", "随便来一个", "帮我做个视频", "来一个", "test", ""}


def is_topic_too_vague(topic: str) -> bool:
    cleaned = topic.strip().lower()
    if len(cleaned) < 5:
        return True
    if cleaned in _VAGUE_INPUTS:
        return True
    return False
