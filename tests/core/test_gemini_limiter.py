"""The shared Gemini limiter: AIMD concurrency, per-group caps, deadlines."""
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core import gemini_client as gc
from src.core.gemini_limiter import (
    AdaptiveLimiter,
    GeminiDeadlineExceeded,
    configure_limiter,
    group_for_tag,
)


def test_group_for_tag():
    assert group_for_tag("phase10a.summary") == "phase10a"
    assert group_for_tag(None) == "other"


def test_throttle_halves_limit_and_success_restores_it():
    lim = AdaptiveLimiter(max_concurrency=8, cooldown_s=0, grow_after=2)
    with lim.slot("g") as slot:
        slot["throttled"] = True
    assert int(lim.limit) == 4 and lim.stats["throttled"] == 1
    for _ in range(8):
        with lim.slot("g"):
            pass
    assert int(lim.limit) == 8


def test_cooldown_applies_to_every_caller():
    lim = AdaptiveLimiter(max_concurrency=4, cooldown_s=0.3)
    with lim.slot("a") as slot:
        slot["throttled"] = True
    started = time.monotonic()
    with lim.slot("b"):  # a different group still waits out the cool-down
        pass
    assert time.monotonic() - started >= 0.25


def test_group_cap_bounds_in_flight():
    lim = AdaptiveLimiter(max_concurrency=10, group_caps={"g": 2}, cooldown_s=0)
    peak, in_flight, lock = [0], [0], threading.Lock()

    def work():
        with lim.slot("g"):
            with lock:
                in_flight[0] += 1
                peak[0] = max(peak[0], in_flight[0])
            time.sleep(0.02)
            with lock:
                in_flight[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 2


def test_deadline_fails_fast():
    lim = AdaptiveLimiter(cooldown_s=0)
    lim.set_deadline("phase10b", 0.01)
    time.sleep(0.02)
    with pytest.raises(GeminiDeadlineExceeded):
        lim.acquire("phase10b")
    lim.acquire("phase10a")  # other groups are unaffected
    with pytest.raises(GeminiDeadlineExceeded):
        lim.backoff(5, "phase10b")


def test_generate_with_retry_reports_429_to_limiter(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    lim = configure_limiter(max_concurrency=8, cooldown_s=0)
    ok = SimpleNamespace(text="ok", usage_metadata=None, candidates=[])
    client = MagicMock()
    client.models.generate_content.side_effect = [RuntimeError("429 RESOURCE_EXHAUSTED"), ok]
    assert gc.generate_with_retry(client=client, tag="phase10a.x", model="m", contents="c") is ok
    assert lim.stats["throttled"] == 1 and int(lim.limit) == 4


def test_generate_with_retry_stops_at_deadline(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    lim = configure_limiter(cooldown_s=0)
    lim.set_deadline("phase10b", 1)
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("503 UNAVAILABLE")
    with pytest.raises(GeminiDeadlineExceeded):
        gc.generate_with_retry(client=client, tag="phase10b.visual", model="m", contents="c")
    assert gc.get_usage_summary()["totals"]["failed_calls"] == 1
