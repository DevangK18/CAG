"""
Shared Gemini Client Initialization
====================================

Centralized client initialization for Google Gemini Enterprise Agent Platform.
All modules should use get_gemini_client() to ensure consistent configuration.

Configuration:
- Uses vertexai=True for Gemini Enterprise Agent Platform (GCP project billing)
- Uses location="global" as required by Enterprise API
- Authenticates with ADC (service account on GCE/Cloud Run, gcloud locally)
- No API key fallback: AI Studio keys bill separately and hit free-tier limits

Usage accounting:
- generate_with_retry() records token usage, retries, latency and success for
  every logical call in a thread-safe, in-process accumulator.
- Call sites that call the API directly should pass the response to record_usage().
- get_usage_summary() / write_usage_summary(path) / log_usage_summary() report
  totals per model and per tag with an estimated cost; reset_usage() clears them.
- The accumulator is per process: worker processes must return
  get_usage_summary() to the parent, which adds it with merge_usage().
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Global client cache
_gemini_client = None
_client_mode: Optional[str] = None


def get_gemini_client(force_new: bool = False):
    """
    Get or create a Gemini client on GCP Agent Platform (bills to the GCP project).

    Project is taken from GOOGLE_CLOUD_PROJECT, else from ADC.

    Args:
        force_new: Force creation of new client (don't use cache)

    Returns:
        Configured genai.Client instance

    Raises:
        ValueError: If no GCP project can be determined
        google.auth.exceptions.DefaultCredentialsError: If ADC is not configured
        ImportError: If google-genai package is not installed
    """
    global _gemini_client, _client_mode

    if _gemini_client is not None and not force_new:
        return _gemini_client

    try:
        from google import genai
        import google.auth
    except ImportError:
        raise ImportError("google-genai package required. Install: pip install google-genai")

    credentials, auth_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or auth_project
    if not project:
        raise ValueError(
            "No GCP project found. Set GOOGLE_CLOUD_PROJECT or configure ADC "
            "(gcloud auth application-default login)."
        )

    # Use vertexai=True with location="global" (google-genai 1.x has no `enterprise` kwarg; it is the 2.x alias)
    _gemini_client = genai.Client(
        vertexai=True,
        project=project,
        location="global",
        credentials=credentials,
    )
    _client_mode = "enterprise"
    logger.info(f"Gemini client initialized with Enterprise (project={project})")
    return _gemini_client


_TRANSIENT_MARKERS = (
    "429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "Empty response",
)


# Safety cap on retries; the limiter's retry window (~5 min) normally ends them first
MAX_RETRIES = 20


def is_transient(error) -> bool:
    """A busy model, timeout or empty reply: worth another attempt later."""
    return any(marker in str(error) for marker in _TRANSIENT_MARKERS)


def _prompt_size(contents, config=None) -> tuple:
    """(characters of text, number of images or other media) in a request."""
    chars = images = 0

    def visit(item):
        nonlocal chars, images
        if item is None:
            return
        if isinstance(item, str):
            chars += len(item)
        elif isinstance(item, (list, tuple)):
            for sub in item:
                visit(sub)
        elif getattr(item, "parts", None) is not None:
            visit(item.parts)
        elif getattr(item, "text", None):
            chars += len(item.text)
        elif getattr(item, "inline_data", None) is not None or getattr(item, "file_data", None) is not None:
            images += 1
        elif isinstance(item, dict):
            if item.get("text"):
                chars += len(item["text"])
            elif item.get("inline_data") or item.get("file_data"):
                images += 1
            elif item.get("parts"):
                visit(item["parts"])

    visit(contents)
    visit(getattr(config, "system_instruction", None))
    return chars, images


def generate_with_retry(
    client=None, max_retries: Optional[int] = None, tag: Optional[str] = None, **kwargs
):
    """
    client.models.generate_content, admitted by the limiter, retried alone on
    transient errors.

    Agent Platform serves Gemini from shared capacity, so 429 RESOURCE_EXHAUSTED
    can occur on paid projects when a model is busy; it is not a fixed quota and
    succeeds on retry. Empty responses are retried too.

    Every attempt is admitted by the process-wide limiter (gemini_limiter): it
    waits for its model's token budget and in-flight ceiling, and the group's
    deadline (the tag prefix, e.g. "phase10b") stops further attempts. A failed
    attempt waits 1-3 s, doubling up to 30 s, within a ~5 min window; no other
    call waits for it.

    Args:
        client: genai.Client to use (default: shared Agent Platform client)
        max_retries: Retries after the first attempt at most (default: until the
            limiter's retry window is used up)
        tag: Usage-accounting tag (phase or purpose, e.g. "phase10a.summary");
            defaults to the calling module's name

    Returns:
        GenerateContentResponse with non-empty text

    Raises:
        The last error once retries are exhausted, or immediately if non-transient

    Usage: one record per call (not per attempt). Tokens from every attempt that
    returned a response are summed, because rejected responses (empty, MAX_TOKENS)
    are still billed.
    """
    from src.core.gemini_limiter import GeminiDeadlineExceeded, Usage, get_limiter, group_for_tag, is_throttle

    tag = tag or _caller_module()
    model = kwargs.get("model")
    tokens = _empty_tokens()
    started = time.monotonic()
    client = client or get_gemini_client()
    limiter = get_limiter()
    group = group_for_tag(tag)
    config = kwargs.get("config")
    chars, images = _prompt_size(kwargs.get("contents"), config)
    max_output = getattr(config, "max_output_tokens", None)
    seq = None
    attempt = 0
    first_failure = None
    while True:
        try:
            with limiter.attempt(model, group, tag, chars, images, max_output, seq) as outcome:
                seq = outcome["seq"]  # a retry keeps its place in the order
                try:
                    response = client.models.generate_content(**kwargs)
                except Exception as e:
                    outcome["throttled"] = is_throttle(e)
                    raise
                counts = _tokens_from_response(response)
                outcome["usage"] = Usage(
                    prompt=counts["prompt"] + counts["tool_use_prompt"],
                    cached=counts["cached"],
                    output=counts["candidates"] + counts["thoughts"],
                )
            _add_tokens(tokens, counts)
            if not response.text:
                finish_reason = (
                    response.candidates[0].finish_reason if response.candidates else None
                )
                if "MAX_TOKENS" in str(finish_reason):
                    # Deterministic: output budget spent (often on thinking), retrying won't help
                    raise ValueError("No text: max_output_tokens exhausted (finish_reason=MAX_TOKENS)")
                raise ValueError(f"Empty response (finish_reason={finish_reason})")
            _record(model, tag, tokens, retries=attempt,
                    latency_s=time.monotonic() - started, success=True)
            return response
        except Exception as e:
            # The retry window runs from the first failure: time spent waiting for
            # admission or on a long successful-looking call does not use it up
            first_failure = first_failure or time.monotonic()
            out_of_retries = (
                attempt >= (MAX_RETRIES if max_retries is None else max_retries)
                or time.monotonic() - first_failure >= limiter.settings.retry_window_s
            )
            if isinstance(e, GeminiDeadlineExceeded) or not is_transient(e) or out_of_retries:
                _record(model, tag, tokens, retries=attempt,
                        latency_s=time.monotonic() - started, success=False, error=e)
                raise
            delay = limiter.retry_delay(attempt)
            logger.warning(f"Gemini call failed ({e}), retry {attempt + 1} in {delay:.0f}s")
            try:
                limiter.backoff(delay, group)
            except GeminiDeadlineExceeded as deadline_error:
                _record(model, tag, tokens, retries=attempt,
                        latency_s=time.monotonic() - started, success=False, error=deadline_error)
                raise deadline_error from e
            attempt += 1


def get_client_mode() -> Optional[str]:
    """Get the current client mode (always 'enterprise' once initialized)."""
    return _client_mode


def reset_client():
    """Reset the cached client (useful for testing)."""
    global _gemini_client, _client_mode
    _gemini_client = None
    _client_mode = None


# ═══════════════════════════════════════════════════════════════════════════════
# USAGE AND COST ACCOUNTING
# ═══════════════════════════════════════════════════════════════════════════════

# Vertex AI list prices for the global endpoint (the client uses location="global"),
# USD per 1M tokens, checked against cloud.google.com/vertex-ai/generative-ai/pricing
# on 2026-10-04. Regional endpoints cost 10% more.
# Each model has rate periods in date order: "until" is the last day (inclusive) a
# rate applies; the final period has no end. "cached" is the rate for cached input
# tokens. "long_context" rates apply to a request whose prompt exceeds
# "above_prompt_tokens". Thinking tokens bill as output. Unlisted models get
# cost=None: add their published price here rather than guessing.
MODEL_PRICES_USD_PER_1M: Dict[str, List[Dict[str, Any]]] = {
    # Introductory rate through 2026-12-31, then the standard rate
    "gemini-3.8-flash": [
        {"until": "2026-12-31", "input": 0.75, "cached": 0.075, "output": 3.75},
        {"input": 1.50, "cached": 0.15, "output": 7.50},
    ],
    "gemini-3.6-flash": [
        {"until": "2026-12-31", "input": 0.75, "cached": 0.075, "output": 3.75},
        {"input": 1.50, "cached": 0.15, "output": 7.50},
    ],
    "gemini-3.5-flash": [{"input": 1.50, "cached": 0.15, "output": 9.00}],
    "gemini-3.1-pro-preview": [
        {
            "input": 2.00,
            "cached": 0.20,
            "output": 12.00,
            "long_context": {
                "above_prompt_tokens": 200_000, "input": 4.00, "cached": 0.40, "output": 18.00,
            },
        },
    ],
}

PRICE_SOURCE = "Vertex AI global list prices checked 2026-10-04 (USD per 1M tokens)"

# usage_metadata attribute -> token kind
_USAGE_FIELDS = {
    "prompt_token_count": "prompt",
    "cached_content_token_count": "cached",
    "candidates_token_count": "candidates",
    "thoughts_token_count": "thoughts",
    "tool_use_prompt_token_count": "tool_use_prompt",
}
_TOKEN_KINDS = tuple(_USAGE_FIELDS.values())

_usage_lock = threading.Lock()
# (model, tag) -> bucket of counters
_usage: Dict[tuple, Dict[str, Any]] = {}
_warned_unpriced: set = set()


def _empty_tokens() -> Dict[str, int]:
    return {kind: 0 for kind in _TOKEN_KINDS}


def _add_tokens(into: Dict[str, int], other: Dict[str, int]) -> None:
    for kind in _TOKEN_KINDS:
        into[kind] += int(other.get(kind, 0) or 0)


def _tokens_from_response(response) -> Dict[str, int]:
    """Read token counts from response.usage_metadata; missing or non-int fields count as 0."""
    tokens = _empty_tokens()
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return tokens
    for attr, kind in _USAGE_FIELDS.items():
        value = getattr(usage, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            tokens[kind] = value
    return tokens


def _normalize_model(model: Optional[str]) -> str:
    """'publishers/google/models/gemini-x' or 'models/gemini-x' -> 'gemini-x'."""
    if not model:
        return "unknown"
    return str(model).rsplit("/", 1)[-1]


def _caller_module() -> str:
    """Module name of the first caller outside this module (default usage tag)."""
    frame = sys._getframe(1)
    while frame is not None and frame.f_globals.get("__name__") == __name__:
        frame = frame.f_back
    return frame.f_globals.get("__name__", "unknown") if frame is not None else "unknown"


def _price_for(
    model: str, prompt_tokens: int = 0, on: Optional[date] = None
) -> Optional[Dict[str, float]]:
    """Input/output rate for one request on a given day (default today); None if unpriced."""
    periods = MODEL_PRICES_USD_PER_1M.get(model)
    price = None
    if periods:
        day = (on or date.today()).isoformat()
        period = next((p for p in periods if "until" not in p or day <= p["until"]), periods[-1])
        long_context = period.get("long_context")
        rates = long_context if long_context and prompt_tokens > long_context["above_prompt_tokens"] else period
        price = {
            "input": rates["input"],
            "cached": rates.get("cached", rates["input"]),
            "output": rates["output"],
        }
    if price is None:
        with _usage_lock:
            first = model not in _warned_unpriced
            _warned_unpriced.add(model)
        if first:
            logger.warning(
                f"No price for Gemini model '{model}' in MODEL_PRICES_USD_PER_1M; "
                "tokens are recorded but its cost is reported as null"
            )
    return price


def _cost_usd(model: str, tokens: Dict[str, int], on: Optional[date] = None) -> Optional[float]:
    """Estimated cost of one request; None when the model has no price. Thinking bills as output."""
    price = _price_for(model, tokens.get("prompt", 0), on)
    if price is None:
        return None
    # prompt_token_count includes cached tokens, which bill at the cached rate
    cached = min(tokens.get("cached", 0), tokens.get("prompt", 0))
    input_tokens = tokens.get("prompt", 0) - cached + tokens.get("tool_use_prompt", 0)
    output_tokens = tokens.get("candidates", 0) + tokens.get("thoughts", 0)
    return (
        input_tokens * price["input"] + cached * price["cached"] + output_tokens * price["output"]
    ) / 1_000_000


def _new_bucket() -> Dict[str, Any]:
    return {
        "calls": 0,
        "failed_calls": 0,
        "retries": 0,
        "latency_s": 0.0,
        "tokens": _empty_tokens(),
        # Priced per call (rates depend on the date and on each request's prompt size)
        "cost_usd": 0.0,
        "unpriced_calls": 0,
    }


def _record(
    model: Optional[str],
    tag: Optional[str],
    tokens: Dict[str, int],
    retries: int = 0,
    latency_s: Optional[float] = None,
    success: bool = True,
    error: Optional[BaseException] = None,
) -> Dict[str, Any]:
    model = _normalize_model(model)
    tag = tag or "untagged"
    latency_s = float(latency_s or 0.0)
    cost = _cost_usd(model, tokens)

    with _usage_lock:
        bucket = _usage.setdefault((model, tag), _new_bucket())
        bucket["calls"] += 1
        bucket["failed_calls"] += 0 if success else 1
        bucket["retries"] += int(retries)
        bucket["latency_s"] += latency_s
        _add_tokens(bucket["tokens"], tokens)
        if cost is None:
            bucket["unpriced_calls"] += 1
        else:
            bucket["cost_usd"] += cost

    logger.debug(
        f"Gemini usage tag={tag} model={model} ok={success} "
        f"prompt={tokens['prompt']} cached={tokens['cached']} "
        f"candidates={tokens['candidates']} thoughts={tokens['thoughts']} "
        f"retries={retries} latency={latency_s:.2f}s "
        f"cost_usd={'n/a' if cost is None else f'{cost:.6f}'}"
        + (f" error={type(error).__name__}" if error is not None else "")
    )
    return {
        "model": model,
        "tag": tag,
        "success": success,
        "retries": int(retries),
        "latency_s": latency_s,
        "tokens": dict(tokens),
        "estimated_cost_usd": cost,
    }


def record_usage(
    response,
    model: Optional[str],
    tag: Optional[str] = None,
    *,
    success: bool = True,
    retries: int = 0,
    latency_s: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Record one Gemini call made outside generate_with_retry.

    Args:
        response: GenerateContentResponse (or the last streamed chunk, which carries
            usage_metadata); None for a call that failed without a response
        model: Model name passed to generate_content
        tag: Phase or purpose; defaults to the calling module's name
        success: False to count the call as failed
        retries: Retries used before this response
        latency_s: Wall-clock seconds for the call

    Returns:
        The per-call record (model, tag, tokens, cost, ...)
    """
    tokens = _tokens_from_response(response) if response is not None else _empty_tokens()
    return _record(model, tag or _caller_module(), tokens, retries=retries,
                   latency_s=latency_s, success=success)


def _summarize(entries) -> Dict[str, Any]:
    """Aggregate [(model, bucket)] into one totals dict with cost."""
    out = _new_bucket()
    priced_cost = 0.0
    unpriced = set()
    for model, bucket in entries:
        out["calls"] += bucket["calls"]
        out["failed_calls"] += bucket["failed_calls"]
        out["retries"] += bucket["retries"]
        out["latency_s"] += bucket["latency_s"]
        _add_tokens(out["tokens"], bucket["tokens"])
        priced_cost += bucket.get("cost_usd", 0.0)
        if bucket.get("unpriced_calls"):
            unpriced.add(model)
    out["latency_s"] = round(out["latency_s"], 3)
    out["tokens"]["input"] = out["tokens"]["prompt"] + out["tokens"]["tool_use_prompt"]
    out["tokens"]["output"] = out["tokens"]["candidates"] + out["tokens"]["thoughts"]
    # null when any model in this group has no price: a partial sum would understate cost
    out["estimated_cost_usd"] = None if unpriced else round(priced_cost, 6)
    out["estimated_cost_usd_priced_models"] = round(priced_cost, 6)
    out["unpriced_models"] = sorted(unpriced)
    out.pop("cost_usd")
    out.pop("unpriced_calls")
    return out


def get_usage_summary() -> Dict[str, Any]:
    """
    Totals since the last reset_usage(): overall, per model, per tag, and per
    (model, tag) pair (the latter is what merge_usage() consumes).

    Each group has calls, failed_calls, retries, latency_s, tokens
    {prompt, cached, candidates, thoughts, tool_use_prompt, input, output},
    estimated_cost_usd (null if any model in the group is unpriced),
    estimated_cost_usd_priced_models and unpriced_models.
    """
    with _usage_lock:
        snapshot = {
            key: {**bucket, "tokens": dict(bucket["tokens"])}
            for key, bucket in _usage.items()
        }

    models = sorted({m for m, _ in snapshot})
    tags = sorted({t for _, t in snapshot})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "price_source": PRICE_SOURCE,
        "prices_usd_per_1m": {m: [dict(p) for p in periods] for m, periods in MODEL_PRICES_USD_PER_1M.items()},
        "totals": _summarize((m, b) for (m, _), b in snapshot.items()),
        "by_model": {
            model: _summarize((m, b) for (m, _), b in snapshot.items() if m == model)
            for model in models
        },
        "by_tag": {
            tag: _summarize((m, b) for (m, t), b in snapshot.items() if t == tag)
            for tag in tags
        },
        "by_model_tag": [
            {"model": m, "tag": t, **_summarize([(m, b)])}
            for (m, t), b in sorted(snapshot.items())
        ],
    }


def merge_usage(summary: Dict[str, Any]) -> None:
    """Add another process's get_usage_summary() into this process's accumulator."""
    for entry in (summary or {}).get("by_model_tag", []):
        key = (entry["model"], entry["tag"])
        with _usage_lock:
            bucket = _usage.setdefault(key, _new_bucket())
            bucket["calls"] += int(entry.get("calls", 0))
            bucket["failed_calls"] += int(entry.get("failed_calls", 0))
            bucket["retries"] += int(entry.get("retries", 0))
            bucket["latency_s"] += float(entry.get("latency_s", 0.0))
            _add_tokens(bucket["tokens"], entry.get("tokens", {}))
            bucket["cost_usd"] += float(entry.get("estimated_cost_usd_priced_models", 0.0))
            bucket["unpriced_calls"] += int(bool(entry.get("unpriced_models")))


def reset_usage() -> None:
    """Clear all accumulated usage (and the once-per-model price warnings)."""
    with _usage_lock:
        _usage.clear()
        _warned_unpriced.clear()


def write_usage_summary(path: Union[str, Path]) -> Dict[str, Any]:
    """Write get_usage_summary() as JSON to path (parents created); returns the summary."""
    summary = get_usage_summary()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2))
    return summary


def log_usage_summary(summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Log totals (and one line per model) at INFO; returns the summary."""
    summary = summary or get_usage_summary()

    def _line(name: str, g: Dict[str, Any]) -> str:
        cost = g["estimated_cost_usd"]
        cost_text = f"${cost:.4f}" if cost is not None else (
            f"unknown (priced models ${g['estimated_cost_usd_priced_models']:.4f}; "
            f"no price for {', '.join(g['unpriced_models'])})"
        )
        return (
            f"{name}: calls={g['calls']} failed={g['failed_calls']} retries={g['retries']} "
            f"input={g['tokens']['input']} (cached={g['tokens']['cached']}) "
            f"output={g['tokens']['output']} (thoughts={g['tokens']['thoughts']}) "
            f"cost={cost_text}"
        )

    logger.info("Gemini usage " + _line("total", summary["totals"]))
    for model, group in summary["by_model"].items():
        logger.info("Gemini usage   " + _line(model, group))
    return summary
