from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any


START_TIME_ENV = "TIANCE_SHELL_START_NS"
TIMING_ENV = "TIANCE_SHELL_TIMING"

_lock = threading.Lock()
_start_ns = int(os.environ.get(START_TIME_ENV) or time.perf_counter_ns())
_last_ns = _start_ns
_enabled = True


def ensure_start_time_env() -> None:
    os.environ.setdefault(START_TIME_ENV, str(_start_ns))


def set_timing_enabled(default: bool) -> None:
    global _enabled

    configured = os.getenv(TIMING_ENV)
    if configured is None:
        _enabled = default
        return

    _enabled = configured.strip().lower() in {"1", "true", "yes", "on"}


def mark(label: str, **details: object) -> None:
    if not _enabled:
        return

    print(_format_message("shell timing", label, details), flush=True)


@contextmanager
def timed_stage(label: str, **details: object):
    mark(f"{label}: start", **details)
    try:
        yield
    finally:
        mark(f"{label}: done", **details)


def configure_pywebview_timing_logger() -> None:
    if not _enabled:
        return

    logger = logging.getLogger("pywebview")
    for handler in logger.handlers:
        handler.setFormatter(_TimingFormatter("pywebview"))


def install_window_event_timing(window: Any) -> None:
    _add_event_handler(window, "shown", lambda *_: mark("window event: shown"))
    _add_event_handler(window, "before_load", lambda *_: mark("window event: before_load"))
    _add_event_handler(window, "_pywebviewready", lambda *_: mark("window event: pywebviewready"))
    _add_event_handler(window, "loaded", lambda *_: _handle_window_loaded(window))
    _add_event_handler(window, "closing", lambda *_: mark("window event: closing"))
    _add_event_handler(window, "closed", lambda *_: mark("window event: closed"))


def record_browser_mark(label: str, browser_elapsed_ms: float | None = None) -> None:
    if browser_elapsed_ms is None:
        mark(label)
        return

    mark(label, browser=f"{browser_elapsed_ms:.1f}ms")


def _handle_window_loaded(window: Any) -> None:
    mark("window event: loaded")
    _record_browser_performance(window)


def _record_browser_performance(window: Any) -> None:
    evaluate_js = getattr(window, "evaluate_js", None)
    if not callable(evaluate_js):
        return

    script = """
(() => {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.record_startup_mark) return false;

  const send = (label, elapsed) => {
    try {
      api.record_startup_mark(label, Number.isFinite(elapsed) ? elapsed : null);
    } catch (_error) {}
  };

  const nav = performance.getEntriesByType("navigation")[0];
  if (nav) {
    send("browser: navigation start", nav.startTime);
    send("browser: dom interactive", nav.domInteractive);
    send("browser: dom content loaded", nav.domContentLoadedEventEnd);
    send("browser: load event end", nav.loadEventEnd);
  }

  send("browser: pywebview loaded callback", performance.now());
  requestAnimationFrame(() => {
    send("browser: first animation frame after loaded", performance.now());
  });
  return true;
})()
"""
    try:
        evaluate_js(script)
    except Exception as exc:  # pragma: no cover - diagnostic only
        mark("browser performance probe failed", error=type(exc).__name__)


def _add_event_handler(window: Any, event_name: str, handler: Callable[..., object]) -> None:
    events = getattr(window, "events", None)
    event = getattr(events, event_name, None)
    if event is None:
        return

    event += handler


def _format_message(source: str, label: str, details: object | None = None) -> str:
    global _last_ns

    now_ns = time.perf_counter_ns()
    with _lock:
        delta_ms = (now_ns - _last_ns) / 1_000_000
        total_ms = (now_ns - _start_ns) / 1_000_000
        _last_ns = now_ns

    suffix = _format_details(details)
    return f"[{source}] +{delta_ms:8.1f}ms total={total_ms:8.1f}ms {label}{suffix}"


def _format_details(details: object | None) -> str:
    if not isinstance(details, dict) or not details:
        return ""

    pairs = [f"{key}={value}" for key, value in details.items()]
    return " | " + " ".join(pairs)


class _TimingFormatter(logging.Formatter):
    def __init__(self, source: str) -> None:
        super().__init__()
        self._source = source

    def format(self, record: logging.LogRecord) -> str:
        return _format_message(self._source, record.getMessage())
