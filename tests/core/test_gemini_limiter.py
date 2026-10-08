"""The Gemini limiter: a token budget per model, utilisation steps, deadlines (fake clock)."""
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core import gemini_client as gc
from src.core.gemini_limiter import (
    GeminiDeadlineExceeded,
    GeminiLimiter,
    LimiterSettings,
    ModelLimits,
    Usage,
    configure_limiter,
    group_for_tag,
    settings_from_config,
)

PRO, FLASH = "gemini-3.1-pro-preview", "gemini-3.8-flash"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _limiter(clock, **overrides):
    settings = LimiterSettings(
        models={
            PRO: ModelLimits(capacity_tpm=10_000, ceiling=4, output_weight=1),
            FLASH: ModelLimits(capacity_tpm=10_000, ceiling=4, output_weight=1),
        },
        default_output_tokens=0,
        **overrides,
    )
    return GeminiLimiter(settings, clock=clock)


def _submit(lim, model=FLASH, chars=4000, group="phase10b", tag="phase10b.visual"):
    """An attempt whose estimate is chars / 4 tokens (no output estimate)."""
    return lim.submit(model, group, tag, chars=chars)


def test_group_for_tag():
    assert group_for_tag("phase10a.summary") == "phase10a"
    assert group_for_tag(None) == "other"


def test_budget_admits_until_full_then_waits_for_the_window():
    clock = Clock()
    lim = _limiter(clock)
    first = _submit(lim, chars=24_000)  # 6,000 tokens
    second = _submit(lim, chars=24_000)  # would make 12,000 > 10,000
    assert first.admitted_at is not None and second.admitted_at is None
    lim.finish(first, Usage(prompt=6000))
    assert second.admitted_at is None  # the tokens stay in the window after the call ends
    clock.advance(60)
    lim.wait(second)
    assert second.admitted_at == clock.now


def test_ceiling_bounds_calls_in_flight():
    clock = Clock()
    lim = _limiter(clock)
    tickets = [_submit(lim, chars=4) for _ in range(6)]
    assert [t.admitted_at is not None for t in tickets] == [True] * 4 + [False] * 2
    lim.finish(tickets[0], Usage(prompt=1))
    assert tickets[4].admitted_at is not None and tickets[5].admitted_at is None


def test_throttle_on_one_model_delays_nothing_else():
    clock = Clock()
    lim = _limiter(clock)
    flash = _submit(lim)
    lim.finish(flash, throttled=True)
    # Same moment: the other model and the same model both start at once, no cool-down
    pro = _submit(lim, model=PRO, group="phase10a", tag="phase10a.overview")
    again = _submit(lim)
    assert pro.admitted_at == clock.now and again.admitted_at == clock.now
    assert lim.utilisation(FLASH) == 1.0 and lim.utilisation(PRO) == 1.0


def test_throttled_tokens_leave_the_window():
    clock = Clock()
    lim = _limiter(clock)
    big = _submit(lim, chars=36_000)  # 9,000 tokens
    waiting = _submit(lim, chars=8_000)  # 2,000: does not fit
    assert waiting.admitted_at is None
    lim.finish(big, throttled=True)
    assert waiting.admitted_at == clock.now


def test_real_count_replaces_the_estimate():
    clock = Clock()
    lim = _limiter(clock)
    call = _submit(lim, chars=36_000)  # estimate 9,000
    lim.finish(call, Usage(prompt=1000, output=500))
    assert lim.window_tokens(FLASH) == 1500
    assert _submit(lim, chars=32_000).admitted_at is not None  # 8,000 now fits


def test_output_weight_and_cached_tokens_count_like_google():
    lim = GeminiLimiter(LimiterSettings(models={PRO: ModelLimits(500_000, 24, output_weight=6)}))
    assert lim.weigh(PRO, Usage(prompt=1000, cached=500, output=100)) == 500 + 50 + 600


def test_oversize_call_starts_on_an_empty_window_and_is_not_starved():
    clock = Clock()
    lim = _limiter(clock)
    small = _submit(lim, chars=400)
    huge = _submit(lim, chars=200_000)  # 50,000 > the whole 10,000 budget
    later = _submit(lim, chars=400)
    assert small.admitted_at is not None and huge.admitted_at is None
    assert later.admitted_at is None  # served in order: no overtaking the waiting call
    lim.finish(small, Usage(prompt=100))
    clock.advance(61)
    lim.wait(huge)
    assert huge.admitted_at == clock.now


def test_steps_down_only_on_a_sustained_rate():
    clock = Clock()
    lim = _limiter(clock)
    # 4 throttles in 10 attempts: under the minimum count of 5
    for i in range(10):
        lim.finish(_submit(lim, chars=4), throttled=i < 4)
    assert lim.utilisation(FLASH) == 1.0
    # A fifth: 5 of 11 is over 10%
    lim.finish(_submit(lim, chars=4), throttled=True)
    assert lim.utilisation(FLASH) == pytest.approx(0.9)
    # Held for a window: more throttles change nothing yet
    for _ in range(10):
        lim.finish(_submit(lim, chars=4), throttled=True)
    assert lim.utilisation(FLASH) == pytest.approx(0.9)
    clock.advance(30)
    lim.finish(_submit(lim, chars=4), throttled=True)
    assert lim.utilisation(FLASH) == pytest.approx(0.9)


def test_steps_up_after_a_clean_window():
    clock = Clock()
    lim = _limiter(clock)
    for _ in range(5):
        lim.finish(_submit(lim, chars=4), throttled=True)
    assert lim.utilisation(FLASH) == pytest.approx(0.9)
    clock.advance(61)
    for _ in range(3):
        lim.finish(_submit(lim, chars=4))
    assert lim.utilisation(FLASH) == pytest.approx(1.0)
    summary = lim.summary()["models"][FLASH]
    assert summary["steps_down"] == 1 and summary["steps_up"] == 1
    assert summary["by_utilisation"]["1.00"]["throttled"] == 5


def test_never_below_the_floor():
    clock = Clock()
    lim = _limiter(clock)
    for _ in range(20):
        for _ in range(6):
            lim.finish(_submit(lim, chars=4), throttled=True)
        clock.advance(61)
    assert lim.utilisation(FLASH) == pytest.approx(0.3)
    assert lim.summary()["models"][FLASH]["utilisation"]["lowest"] == pytest.approx(0.3)


def test_lower_utilisation_shrinks_the_budget():
    clock = Clock()
    lim = _limiter(clock)
    for _ in range(5):
        lim.finish(_submit(lim, chars=4), throttled=True)
    clock.advance(61)  # the window empties; utilisation is 0.9 until a clean window passes
    first = _submit(lim, chars=32_000)  # 8,000
    second = _submit(lim, chars=4_400)  # 1,100: 9,100 > 9,000
    assert first.admitted_at is not None and second.admitted_at is None


def test_estimate_learns_output_and_image_tokens_per_tag():
    clock = Clock()
    lim = GeminiLimiter(LimiterSettings(models={FLASH: ModelLimits(2_000_000, 64, output_weight=5)}, image_tokens=1000),
                        clock=clock)
    assert lim.estimate(FLASH, "phase10b.visual.table", chars=400, images=1) == 100 + 1000 + 1500 * 5
    for _ in range(5):
        call = lim.submit(FLASH, "phase10b", "phase10b.visual.table", chars=400, images=1)
        lim.finish(call, Usage(prompt=100 + 250, output=200))
    assert lim.estimate(FLASH, "phase10b.visual.table", chars=400, images=1) == 100 + 250 + 200 * 5
    assert lim.estimate(FLASH, "phase10b.visual.table", chars=400, images=1, ) > 0


def test_deadline_fails_fast_and_only_for_its_group():
    clock = Clock()
    lim = _limiter(clock)
    lim.set_deadline("phase10b", 10)
    clock.advance(11)
    with pytest.raises(GeminiDeadlineExceeded):
        _submit(lim)
    assert _submit(lim, model=PRO, group="phase10a", tag="phase10a.x").admitted_at is not None
    with pytest.raises(GeminiDeadlineExceeded):
        lim.backoff(5, "phase10b")


def test_waiting_call_raises_when_its_deadline_passes():
    lim = GeminiLimiter(LimiterSettings(models={FLASH: ModelLimits(capacity_tpm=1000, ceiling=1)}))
    held = lim.submit(FLASH, "phase10b", "t", chars=40)
    lim.set_deadline("phase10b", 0.05)
    waiting = lim.submit(FLASH, "phase10b", "t", chars=40)
    started = time.monotonic()
    with pytest.raises(GeminiDeadlineExceeded):
        lim.wait(waiting)
    assert time.monotonic() - started < 1
    lim.finish(held, Usage(prompt=10))


def test_threads_wait_and_are_released():
    lim = GeminiLimiter(LimiterSettings(models={FLASH: ModelLimits(capacity_tpm=10**9, ceiling=2)}))
    peak, in_flight, lock = [0], [0], threading.Lock()

    def work():
        with lim.attempt(FLASH, "phase10b", "t", chars=4) as outcome:
            with lock:
                in_flight[0] += 1
                peak[0] = max(peak[0], in_flight[0])
            time.sleep(0.02)
            with lock:
                in_flight[0] -= 1
            outcome["usage"] = Usage(prompt=1)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 2
    summary = lim.summary()["models"][FLASH]
    assert summary["calls"] == 8 and summary["peak_in_flight"] == 2 and summary["wait_ceiling_s"] > 0


def test_settings_from_config():
    from src.parsing_pipeline.config import ParsingPipelineConfig

    settings = settings_from_config(ParsingPipelineConfig.from_yaml().gemini)
    assert settings.models[PRO].capacity_tpm == 500_000 and settings.models[PRO].ceiling == 24
    assert settings.models[FLASH].capacity_tpm == 2_000_000 and settings.models[FLASH].ceiling == 64
    assert settings.models[FLASH].output_weight == 5
    assert settings.retry_first_wait_s == (1, 3)


def test_generate_with_retry_retries_a_429_alone(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    lim = configure_limiter(LimiterSettings())
    ok = SimpleNamespace(text="ok", usage_metadata=None, candidates=[])
    client = MagicMock()
    client.models.generate_content.side_effect = [RuntimeError("429 RESOURCE_EXHAUSTED"), ok]
    assert gc.generate_with_retry(client=client, tag="phase10a.x", model="m", contents="c") is ok
    summary = lim.summary()["models"]["m"]
    assert summary["throttled"] == 1 and summary["calls"] == 2
    assert summary["utilisation"]["final"] == 1.0


def test_retry_waits_start_small_and_are_capped():
    lim = GeminiLimiter(LimiterSettings())
    assert 1 <= lim.retry_delay(0) <= 3
    assert 2 <= lim.retry_delay(1) <= 6
    assert lim.retry_delay(10) == 30


def test_generate_with_retry_stops_at_deadline(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    lim = configure_limiter(LimiterSettings())
    lim.set_deadline("phase10b", 1)
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("503 UNAVAILABLE")
    with pytest.raises(GeminiDeadlineExceeded):
        gc.generate_with_retry(client=client, tag="phase10b.visual", model="m", contents="c")
    assert gc.get_usage_summary()["totals"]["failed_calls"] == 1


def test_prompt_size_counts_text_and_images():
    from google.genai import types

    contents = [types.Part.from_text(text="abcd"), types.Part.from_bytes(data=b"x", mime_type="image/png"), "ef"]
    config = types.GenerateContentConfig(system_instruction="ghi")
    assert gc._prompt_size(contents, config) == (9, 1)
