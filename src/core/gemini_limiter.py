"""
Process-wide limiter for Gemini calls: a token budget per model.

Every attempt made through gemini_client.generate_with_retry is admitted here:

- State is kept per model. Nothing that happens on one model affects another.
- Each model has a budget of capacity x utilisation tokens per rolling window
  (60 s by default). An attempt starts when the tokens admitted in the window
  plus its own estimate fit the budget, and the model's in-flight calls are
  under its ceiling. An attempt larger than the whole budget starts once the
  window is empty. Waiting attempts are served in arrival order, so a large
  one is never starved by small ones.
- Tokens are counted as Google's throughput metric counts them: input, cached
  input at a reduced weight and output (thinking included) at the model's
  output weight. The estimate is replaced by the real count when the response
  arrives; a 429's tokens leave the window.
- A 429 retries that attempt alone. Utilisation steps down only while 429s stay
  high over a window, holds for a window after any step, and steps back up
  after a clean window, never below the floor.
- An optional deadline per group (the tag prefix: phase9, phase10a, phase10b).
  Once it passes, new attempts and retries fail fast with
  GeminiDeadlineExceeded, so a phase cannot run past its time budget.

The clock is injectable so the rules can be tested without waiting.
"""

import heapq
import itertools
import logging
import random
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

THROTTLE_MARKERS = ("429", "RESOURCE_EXHAUSTED")


class GeminiDeadlineExceeded(RuntimeError):
    """A group's deadline passed before the request could be sent or retried."""


def group_for_tag(tag: Optional[str]) -> str:
    """'phase10a.summary' -> 'phase10a'."""
    return (tag or "other").split(".")[0]


def is_throttle(error: BaseException) -> bool:
    return any(marker in str(error) for marker in THROTTLE_MARKERS)


def normalize_model(model: Optional[str]) -> str:
    """'publishers/google/models/gemini-x' -> 'gemini-x'."""
    return str(model or "unknown").rsplit("/", 1)[-1]


@dataclass
class ModelLimits:
    capacity_tpm: int
    """Tokens per minute at 100% utilisation (weighted as below)."""
    ceiling: int
    """Calls in flight at most."""
    output_weight: float = 1.0
    """Weight of an output (and thinking) token in the budget."""
    cached_weight: float = 0.1
    """Weight of a cached input token."""


@dataclass
class LimiterSettings:
    models: Dict[str, ModelLimits] = field(default_factory=dict)
    default: ModelLimits = field(
        default_factory=lambda: ModelLimits(capacity_tpm=500_000, ceiling=16, output_weight=6.0)
    )
    window_s: float = 60.0
    start_utilisation: float = 1.0
    max_utilisation: float = 1.0
    min_utilisation: float = 0.30
    step: float = 0.10
    step_down_rate: float = 0.10
    step_down_min_throttles: int = 5
    step_up_rate: float = 0.02
    hold_s: float = 60.0
    image_tokens: int = 1100
    """Input tokens per image until a tag has `min_real_counts` real counts."""
    default_output_tokens: int = 1500
    """Output tokens assumed for a tag with no real count yet (capped by max_output_tokens)."""
    min_real_counts: int = 5
    retry_first_wait_s: Tuple[float, float] = (1.0, 3.0)
    retry_max_wait_s: float = 30.0
    retry_window_s: float = 300.0


@dataclass
class Usage:
    """Token counts of one response (from usage_metadata)."""

    prompt: int = 0
    cached: int = 0
    output: int = 0


class _Ticket:
    __slots__ = ("seq", "model", "group", "tag", "chars", "images", "estimate", "queued_at", "admitted_at", "tokens")

    def __init__(self, seq: int, model: str, group: str, tag: str, chars: int, images: int):
        self.seq = seq
        self.model = model
        self.group = group
        self.tag = tag
        self.chars = chars
        self.images = images
        self.estimate = 0
        self.queued_at = 0.0
        self.admitted_at: Optional[float] = None
        self.tokens = 0  # tokens this attempt holds in the window


class _TagEstimate:
    """Running averages per tag: output tokens and input tokens per image."""

    def __init__(self):
        self.outputs = 0
        self.output_sum = 0
        self.image_counts = 0
        self.image_token_sum = 0.0


class _ModelState:
    def __init__(self, name: str, limits: ModelLimits, utilisation: float):
        self.name = name
        self.limits = limits
        self.utilisation = utilisation
        self.window: Dict[int, Tuple[float, int]] = {}  # seq -> (admitted_at, tokens)
        self.queue: List[Tuple[int, _Ticket]] = []  # heap by arrival order
        self.in_flight = 0
        self.attempts: Deque[Tuple[float, bool]] = deque()
        self.last_step_at = float("-inf")
        self.blocked_reason: Optional[str] = None
        self.blocked_since = 0.0
        # Real tokens by completion time, for tokens per minute
        self.completed: Deque[Tuple[float, int]] = deque()
        self.completed_sum = 0
        self.first_at: Optional[float] = None
        self.last_at: Optional[float] = None
        self.util_changed_at: Optional[float] = None
        self.stats = {
            "calls": 0,
            "throttled": 0,
            "tokens": 0,
            "peak_tpm": 0,
            "lowest_utilisation": utilisation,
            "steps_down": 0,
            "steps_up": 0,
            "wait_budget_s": 0.0,
            "wait_ceiling_s": 0.0,
            "peak_in_flight": 0,
            "utilisation_seconds": 0.0,
            "budget_tokens": 0.0,  # sum of budget x time while active
            "by_utilisation": {},  # "0.9" -> {"attempts", "throttled"}
        }

    def budget(self, window_s: float = 60.0) -> float:
        """Tokens allowed per window at the current utilisation."""
        return self.limits.capacity_tpm * window_s / 60.0 * self.utilisation


class GeminiLimiter:
    def __init__(self, settings: Optional[LimiterSettings] = None, clock: Callable[[], float] = time.monotonic):
        self.settings = settings or LimiterSettings()
        self.clock = clock
        self._cond = threading.Condition()
        self._seq = itertools.count()
        self._models: Dict[str, _ModelState] = {}
        self._tags: Dict[str, _TagEstimate] = {}
        self._deadlines: Dict[str, float] = {}
        self._groups: Dict[str, Dict[str, float]] = {}

    # ── configuration ──────────────────────────────────────────────────────

    def limits(self, model: Optional[str]) -> ModelLimits:
        return self.settings.models.get(normalize_model(model), self.settings.default)

    def ceiling(self, model: Optional[str]) -> int:
        return self.limits(model).ceiling

    def _state(self, model: str) -> _ModelState:
        state = self._models.get(model)
        if state is None:
            state = _ModelState(model, self.limits(model), self.settings.start_utilisation)
            self._models[model] = state
        return state

    # ── deadlines ──────────────────────────────────────────────────────────

    def set_deadline(self, group: str, seconds: Optional[float]) -> None:
        """Requests in `group` fail fast `seconds` from now (None clears it)."""
        with self._cond:
            if seconds:
                self._deadlines[group] = self.clock() + seconds
            else:
                self._deadlines.pop(group, None)
            self._cond.notify_all()

    def _past_deadline(self, group: str, now: float) -> bool:
        deadline = self._deadlines.get(group)
        return deadline is not None and now >= deadline

    # ── estimates ──────────────────────────────────────────────────────────

    def weigh(self, model: str, usage: Usage) -> int:
        """Tokens of one response as the budget counts them."""
        limits = self.limits(model)
        cached = min(usage.cached, usage.prompt)
        return int(round(usage.prompt - cached + cached * limits.cached_weight + usage.output * limits.output_weight))

    def estimate(self, model: str, tag: str, chars: int, images: int = 0, max_output: Optional[int] = None) -> int:
        """Prompt characters / 4, plus images, plus the tag's average output (weighted)."""
        s = self.settings
        stats = self._tags.get(tag)
        per_image = s.image_tokens
        output = s.default_output_tokens
        if stats is not None:
            if stats.image_counts >= s.min_real_counts:
                per_image = stats.image_token_sum / stats.image_counts
            if stats.outputs:
                output = stats.output_sum / stats.outputs
        if max_output:
            output = min(output, max_output)
        limits = self.limits(model)
        return int(chars / 4 + images * per_image + output * limits.output_weight)

    def _learn(self, ticket: _Ticket, usage: Usage) -> None:
        stats = self._tags.setdefault(ticket.tag, _TagEstimate())
        stats.outputs += 1
        stats.output_sum += usage.output
        if ticket.images:
            stats.image_counts += 1
            stats.image_token_sum += max(usage.prompt - ticket.chars / 4, 0) / ticket.images

    # ── admission ──────────────────────────────────────────────────────────

    def _purge(self, state: _ModelState, now: float) -> None:
        horizon = now - self.settings.window_s
        for seq in [seq for seq, (at, _) in state.window.items() if at <= horizon]:
            del state.window[seq]
        while state.attempts and state.attempts[0][0] <= horizon:
            state.attempts.popleft()
        while state.completed and state.completed[0][0] <= horizon:
            state.completed_sum -= state.completed.popleft()[1]

    def window_tokens(self, model: str, now: Optional[float] = None) -> int:
        with self._cond:
            state = self._state(normalize_model(model))
            self._purge(state, self.clock() if now is None else now)
            return sum(tokens for _, tokens in state.window.values())

    def _block(self, state: _ModelState, reason: Optional[str], now: float) -> None:
        """Time the head of the queue spends blocked, by cause."""
        if state.blocked_reason == reason:
            return
        if state.blocked_reason is not None:
            state.stats[f"wait_{state.blocked_reason}_s"] += now - state.blocked_since
        state.blocked_reason = reason
        state.blocked_since = now

    def _admit_head(self, state: _ModelState, now: float) -> None:
        """Admit waiting attempts in order while they fit."""
        self._purge(state, now)
        while state.queue:
            ticket = state.queue[0][1]
            if state.in_flight >= state.limits.ceiling:
                self._block(state, "ceiling", now)
                return
            used = sum(tokens for _, tokens in state.window.values())
            if state.window and used + ticket.estimate > state.budget(self.settings.window_s):
                self._block(state, "budget", now)
                return
            heapq.heappop(state.queue)
            self._block(state, None, now)
            ticket.admitted_at = now
            ticket.tokens = ticket.estimate
            state.window[ticket.seq] = (now, ticket.tokens)
            state.in_flight += 1
            state.stats["peak_in_flight"] = max(state.stats["peak_in_flight"], state.in_flight)
            self._activity(state, now)

    def _drop_expired(self, state: _ModelState, now: float) -> None:
        """Waiting attempts whose group deadline passed leave the queue (their callers raise)."""
        expired = [entry for entry in state.queue if self._past_deadline(entry[1].group, now)]
        if expired:
            state.queue = [entry for entry in state.queue if entry not in expired]
            heapq.heapify(state.queue)

    def submit(
        self,
        model: str,
        group: str,
        tag: str,
        chars: int = 0,
        images: int = 0,
        max_output: Optional[int] = None,
        seq: Optional[int] = None,
        now: Optional[float] = None,
    ) -> _Ticket:
        """Queue one attempt (no waiting). `seq` keeps a retry's place in the order."""
        model = normalize_model(model)
        with self._cond:
            now = self.clock() if now is None else now
            if self._past_deadline(group, now):
                raise GeminiDeadlineExceeded(f"{group} time budget used up")
            ticket = _Ticket(next(self._seq) if seq is None else seq, model, group, tag, chars, images)
            ticket.estimate = self.estimate(model, tag, chars, images, max_output)
            ticket.queued_at = now
            state = self._state(model)
            heapq.heappush(state.queue, (ticket.seq, ticket))
            self._admit_head(state, now)
            return ticket

    def wait(self, ticket: _Ticket) -> None:
        """Block until the attempt is admitted, or raise when its group's deadline passes."""
        with self._cond:
            state = self._state(ticket.model)
            while ticket.admitted_at is None:
                now = self.clock()
                self._admit_head(state, now)
                if ticket.admitted_at is not None:
                    break
                if self._past_deadline(ticket.group, now):
                    self._drop_expired(state, now)
                    self._admit_head(state, now)
                    self._cond.notify_all()
                    raise GeminiDeadlineExceeded(f"{ticket.group} time budget used up")
                timeout = 1.0
                if state.window:
                    oldest = min(at for at, _ in state.window.values())
                    timeout = min(timeout, max(oldest + self.settings.window_s - now, 0.01))
                deadline = self._deadlines.get(ticket.group)
                if deadline is not None:
                    timeout = min(timeout, max(deadline - now, 0.01))
                self._cond.wait(timeout=timeout)
            group = self._groups.setdefault(ticket.group, {"calls": 0, "throttled": 0, "wait_s": 0.0})
            group["wait_s"] += ticket.admitted_at - ticket.queued_at

    def finish(
        self,
        ticket: _Ticket,
        usage: Optional[Usage] = None,
        throttled: bool = False,
        now: Optional[float] = None,
    ) -> None:
        """
        End an admitted attempt. With usage, the estimate is replaced by the real
        count; a 429 removes its tokens from the window; any other failure keeps
        the estimate.
        """
        with self._cond:
            now = self.clock() if now is None else now
            state = self._state(ticket.model)
            state.in_flight -= 1
            if ticket.seq in state.window:
                at, _ = state.window[ticket.seq]
                if throttled:
                    del state.window[ticket.seq]
                elif usage is not None:
                    state.window[ticket.seq] = (at, self.weigh(ticket.model, usage))
            if usage is not None:
                real = self.weigh(ticket.model, usage)
                self._learn(ticket, usage)
                state.stats["tokens"] += real
                state.completed.append((now, real))
                state.completed_sum += real
                self._purge(state, now)
                state.stats["peak_tpm"] = max(state.stats["peak_tpm"], state.completed_sum)
            state.stats["calls"] += 1
            group = self._groups.setdefault(ticket.group, {"calls": 0, "throttled": 0, "wait_s": 0.0})
            group["calls"] += 1
            if throttled:
                state.stats["throttled"] += 1
                group["throttled"] += 1
            self._record_attempt(state, throttled, now)
            self._activity(state, now)
            self._admit_head(state, now)
            self._cond.notify_all()

    @contextmanager
    def attempt(self, model: str, group: str, tag: str, chars: int = 0, images: int = 0,
                max_output: Optional[int] = None, seq: Optional[int] = None):
        """
        Hold an admission for one attempt. The body sets outcome['usage'] (a Usage)
        on a response, or outcome['throttled'] on a 429.
        """
        ticket = self.submit(model, group, tag, chars, images, max_output, seq)
        self.wait(ticket)
        outcome = {"usage": None, "throttled": False, "seq": ticket.seq}
        try:
            yield outcome
        finally:
            self.finish(ticket, outcome["usage"], outcome["throttled"])

    # ── utilisation ────────────────────────────────────────────────────────

    def _activity(self, state: _ModelState, now: float) -> None:
        """Integrate utilisation and budget over the time the model is in use."""
        if state.first_at is None:
            state.first_at = now
            state.util_changed_at = now
        elapsed = now - state.util_changed_at
        if elapsed > 0:
            state.stats["utilisation_seconds"] += elapsed * state.utilisation
            state.stats["budget_tokens"] += elapsed / 60.0 * state.budget()  # per minute
            state.util_changed_at = now
        state.last_at = now

    def _record_attempt(self, state: _ModelState, throttled: bool, now: float) -> None:
        s = self.settings
        level = f"{state.utilisation:.2f}"
        bucket = state.stats["by_utilisation"].setdefault(level, {"attempts": 0, "throttled": 0})
        bucket["attempts"] += 1
        bucket["throttled"] += int(throttled)
        state.attempts.append((now, throttled))
        self._purge(state, now)
        if now - state.last_step_at < s.hold_s:
            return
        attempts = len(state.attempts)
        throttles = sum(1 for _, t in state.attempts if t)
        new = state.utilisation
        if throttles >= s.step_down_min_throttles and throttles / attempts >= s.step_down_rate:
            new = max(s.min_utilisation, round(state.utilisation - s.step, 4))
        elif attempts and throttles / attempts < s.step_up_rate:
            new = min(s.max_utilisation, round(state.utilisation + s.step, 4))
        if new == state.utilisation:
            return
        self._activity(state, now)
        direction = "down" if new < state.utilisation else "up"
        state.stats[f"steps_{direction}"] += 1
        state.utilisation = new
        state.last_step_at = now
        state.stats["lowest_utilisation"] = min(state.stats["lowest_utilisation"], new)
        logger.info(
            f"Gemini {state.name}: utilisation {direction} to {new:.0%} "
            f"({throttles} of {attempts} attempts throttled in the last {s.window_s:.0f}s)"
        )

    def utilisation(self, model: str) -> float:
        with self._cond:
            return self._state(normalize_model(model)).utilisation

    # ── retries ────────────────────────────────────────────────────────────

    def retry_delay(self, retry: int) -> float:
        """Wait before retry number `retry` (0-based): 1-3 s, doubling, capped."""
        low, high = self.settings.retry_first_wait_s
        return min(random.uniform(low, high) * 2**retry, self.settings.retry_max_wait_s)

    def backoff(self, seconds: float, group: str) -> None:
        """Sleep before a retry, unless that would run past the group's deadline."""
        deadline = self._deadlines.get(group)
        if deadline is not None and self.clock() + seconds > deadline:
            raise GeminiDeadlineExceeded(f"{group} time budget used up before retry")
        time.sleep(seconds)

    # ── statistics ─────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Dict]:
        """Per-model counters (cumulative), for differences between two moments."""
        with self._cond:
            now = self.clock()
            out = {}
            for name, state in self._models.items():
                if state.first_at is not None:
                    self._activity(state, now)
                out[name] = {"tokens": state.stats["tokens"], "budget_tokens": state.stats["budget_tokens"], "at": now}
            return out

    def summary(self, since: Optional[Dict[str, Dict]] = None) -> Dict[str, Dict]:
        """One entry per model; `since` (a snapshot) adds the share of the budget used after it."""
        with self._cond:
            now = self.clock()
            out: Dict[str, Dict] = {"models": {}, "groups": {}}
            for name, state in sorted(self._models.items()):
                if state.first_at is None:
                    continue
                self._activity(state, now)
                if state.blocked_reason is not None:  # count the wait still running
                    state.stats[f"wait_{state.blocked_reason}_s"] += now - state.blocked_since
                    state.blocked_since = now
                st = state.stats
                active_s = max((state.last_at or now) - state.first_at, 1e-9)
                attempts = st["calls"]
                entry = {
                    "capacity_tpm": state.limits.capacity_tpm,
                    "ceiling": state.limits.ceiling,
                    "output_weight": state.limits.output_weight,
                    "utilisation": {
                        "lowest": st["lowest_utilisation"],
                        "average": round(st["utilisation_seconds"] / active_s, 3) if active_s > 1e-6 else state.utilisation,
                        "final": state.utilisation,
                    },
                    "tokens_per_minute": {
                        "peak": st["peak_tpm"],
                        "average": round(st["tokens"] / (active_s / 60.0)) if active_s > 1 else st["tokens"],
                    },
                    "budget_share": round(st["tokens"] / st["budget_tokens"], 3) if st["budget_tokens"] else None,
                    "calls": attempts,
                    "throttled": st["throttled"],
                    "throttle_rate": round(st["throttled"] / attempts, 4) if attempts else 0.0,
                    "steps_down": st["steps_down"],
                    "steps_up": st["steps_up"],
                    "wait_budget_s": round(st["wait_budget_s"], 1),
                    "wait_ceiling_s": round(st["wait_ceiling_s"], 1),
                    "peak_in_flight": st["peak_in_flight"],
                    "active_minutes": round(active_s / 60.0, 1),
                    "by_utilisation": {
                        level: {**b, "rate": round(b["throttled"] / b["attempts"], 4) if b["attempts"] else 0.0}
                        for level, b in sorted(st["by_utilisation"].items(), reverse=True)
                    },
                }
                if since and name in since:
                    used = st["tokens"] - since[name]["tokens"]
                    budget = st["budget_tokens"] - since[name]["budget_tokens"]
                    entry["budget_share_since"] = round(used / budget, 3) if budget > 0 else None
                out["models"][name] = entry
            out["groups"] = {
                g: {**v, "wait_s": round(v["wait_s"], 1)} for g, v in sorted(self._groups.items())
            }
            return out


_limiter: Optional[GeminiLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter() -> GeminiLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = GeminiLimiter(settings_from_config())
        return _limiter


def configure_limiter(settings: Optional[LimiterSettings] = None, **kwargs) -> GeminiLimiter:
    """Replace the process-wide limiter (call before any Gemini request)."""
    global _limiter
    with _limiter_lock:
        _limiter = GeminiLimiter(settings or settings_from_config(), **kwargs)
        return _limiter


def reset_limiter() -> None:
    global _limiter
    with _limiter_lock:
        _limiter = None


def settings_from_config(cfg=None) -> LimiterSettings:
    """LimiterSettings from the `gemini:` block of parsing_config.yaml."""
    if cfg is None:
        try:
            from src.parsing_pipeline.config import get_config

            cfg = get_config().gemini
        except Exception:  # the API and scripts may run without the pipeline config
            return LimiterSettings()
    models = {
        name: ModelLimits(**{k: v for k, v in values.items() if k in ModelLimits.__dataclass_fields__})
        for name, values in (cfg.models or {}).items()
    }
    default = cfg.default_model or {}
    return LimiterSettings(
        models=models,
        default=ModelLimits(**{k: v for k, v in default.items() if k in ModelLimits.__dataclass_fields__})
        if default
        else LimiterSettings().default,
        window_s=cfg.window_seconds,
        start_utilisation=cfg.start_utilisation,
        max_utilisation=cfg.max_utilisation,
        min_utilisation=cfg.min_utilisation,
        step=cfg.utilisation_step,
        step_down_rate=cfg.step_down_rate,
        step_down_min_throttles=cfg.step_down_min_throttles,
        step_up_rate=cfg.step_up_rate,
        hold_s=cfg.hold_seconds,
        image_tokens=cfg.image_tokens,
        default_output_tokens=cfg.default_output_tokens,
        retry_first_wait_s=tuple(cfg.retry_first_wait_seconds),
        retry_max_wait_s=cfg.retry_max_wait_seconds,
        retry_window_s=cfg.retry_window_seconds,
    )
