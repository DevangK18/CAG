"""
Process-wide adaptive limiter for Gemini calls.

Every request made through gemini_client.generate_with_retry takes a slot here:

- One concurrency limit for the whole process. A 429 halves it and starts a
  shared cool-down, so a busy model slows every caller, not only the one that
  saw the 429. It grows back by one after `grow_after` successes in a row (AIMD).
- A cap per group (the tag prefix: phase9, phase10a, phase10b, ...), so one
  phase cannot take every slot.
- An optional deadline per group. Once it passes, new requests and retries fail
  fast with GeminiDeadlineExceeded instead of waiting, so a phase cannot run
  past its time budget; the caller records the lost items.

Agent Platform serves Gemini from shared capacity (Dynamic Shared Quota), so
there is no fixed RPM to configure; the limit adapts to what the model accepts.
"""

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# In-flight requests allowed per group when not configured otherwise
DEFAULT_GROUP_CAPS: Dict[str, int] = {"phase9": 4, "phase10a": 8, "phase10b": 8}

THROTTLE_MARKERS = ("429", "RESOURCE_EXHAUSTED")


class GeminiDeadlineExceeded(RuntimeError):
    """A group's deadline passed before the request could be sent or retried."""


def group_for_tag(tag: Optional[str]) -> str:
    """'phase10a.summary' -> 'phase10a'."""
    return (tag or "other").split(".")[0]


def is_throttle(error: BaseException) -> bool:
    return any(marker in str(error) for marker in THROTTLE_MARKERS)


class AdaptiveLimiter:
    def __init__(
        self,
        max_concurrency: Optional[int] = None,
        group_caps: Optional[Dict[str, int]] = None,
        min_concurrency: int = 1,
        cooldown_s: float = 10.0,
        grow_after: int = 10,
    ):
        self.max_concurrency = max_concurrency or int(
            os.getenv("GEMINI_MAX_CONCURRENCY", "16")
        )
        self.min_concurrency = min_concurrency
        self.cooldown_s = cooldown_s
        self.grow_after = grow_after
        self.group_caps = {**DEFAULT_GROUP_CAPS, **(group_caps or {})}
        self.limit = float(self.max_concurrency)
        self._cond = threading.Condition()
        self._in_flight = 0
        self._group_in_flight: Dict[str, int] = {}
        self._cooldown_until = 0.0
        self._successes = 0
        self._deadlines: Dict[str, float] = {}
        self.stats = {
            "throttled": 0,
            "lowest_limit": self.max_concurrency,
            "wait_s": 0.0,
        }

    # ── deadlines ──────────────────────────────────────────────────────────

    def set_deadline(self, group: str, seconds: Optional[float]) -> None:
        """Requests in `group` fail fast `seconds` from now (None clears it)."""
        with self._cond:
            if seconds:
                self._deadlines[group] = time.monotonic() + seconds
            else:
                self._deadlines.pop(group, None)
            self._cond.notify_all()

    def _past_deadline(self, group: str, now: float) -> bool:
        deadline = self._deadlines.get(group)
        return deadline is not None and now >= deadline

    # ── slots ──────────────────────────────────────────────────────────────

    def acquire(self, group: str) -> None:
        started = time.monotonic()
        with self._cond:
            while True:
                now = time.monotonic()
                if self._past_deadline(group, now):
                    raise GeminiDeadlineExceeded(f"{group} time budget used up")
                cap = self.group_caps.get(group)
                if (
                    now >= self._cooldown_until
                    and self._in_flight < max(int(self.limit), self.min_concurrency)
                    and (cap is None or self._group_in_flight.get(group, 0) < cap)
                ):
                    self._in_flight += 1
                    self._group_in_flight[group] = (
                        self._group_in_flight.get(group, 0) + 1
                    )
                    self.stats["wait_s"] += now - started
                    return
                # Woken by release(); otherwise re-check when the cool-down or deadline ends
                timeout = max(self._cooldown_until - now, 0) or 1.0
                deadline = self._deadlines.get(group)
                if deadline is not None:
                    timeout = min(timeout, max(deadline - now, 0.01))
                self._cond.wait(timeout=timeout)

    def release(self, group: str, throttled: bool = False) -> None:
        with self._cond:
            self._in_flight -= 1
            self._group_in_flight[group] -= 1
            if throttled:
                self.limit = max(float(self.min_concurrency), self.limit / 2)
                self._cooldown_until = max(
                    self._cooldown_until, time.monotonic() + self.cooldown_s
                )
                self._successes = 0
                self.stats["throttled"] += 1
                self.stats["lowest_limit"] = min(
                    self.stats["lowest_limit"], int(self.limit)
                )
                logger.info(
                    f"Gemini 429: concurrency limit now {int(self.limit)}, cooling down {self.cooldown_s:.0f}s"
                )
            else:
                self._successes += 1
                if (
                    self._successes >= self.grow_after
                    and self.limit < self.max_concurrency
                ):
                    self.limit = min(float(self.max_concurrency), self.limit + 1)
                    self._successes = 0
            self._cond.notify_all()

    @contextmanager
    def slot(self, group: str):
        """Hold a slot for one request; set outcome['throttled'] on a 429."""
        self.acquire(group)
        outcome = {"throttled": False}
        try:
            yield outcome
        finally:
            self.release(group, outcome["throttled"])

    def backoff(self, seconds: float, group: str) -> None:
        """Sleep before a retry, unless that would run past the group's deadline."""
        deadline = self._deadlines.get(group)
        if deadline is not None and time.monotonic() + seconds > deadline:
            raise GeminiDeadlineExceeded(f"{group} time budget used up before retry")
        time.sleep(seconds)


_limiter: Optional[AdaptiveLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter() -> AdaptiveLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = AdaptiveLimiter()
        return _limiter


def configure_limiter(**kwargs) -> AdaptiveLimiter:
    """Replace the process-wide limiter (call before any Gemini request)."""
    global _limiter
    with _limiter_lock:
        _limiter = AdaptiveLimiter(**kwargs)
        return _limiter


def reset_limiter() -> None:
    global _limiter
    with _limiter_lock:
        _limiter = None
