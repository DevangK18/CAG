"""Usage and cost accounting in src.core.gemini_client (API fully mocked)."""

import asyncio
import json
import logging
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core import gemini_client as gc


def _response(text="ok", prompt=100, candidates=20, thoughts=5, cached=0, finish="STOP"):
    usage = SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        cached_content_token_count=cached,
        tool_use_prompt_token_count=None,
        total_token_count=prompt + candidates + thoughts,
    )
    return SimpleNamespace(
        text=text,
        usage_metadata=usage,
        candidates=[SimpleNamespace(finish_reason=finish)],
    )


def _client(*side_effect):
    client = MagicMock()
    client.models.generate_content.side_effect = list(side_effect)
    return client


@pytest.fixture(autouse=True)
def _clean_usage():
    gc.reset_usage()
    yield
    gc.reset_usage()


@pytest.fixture
def no_sleep():
    with patch("time.sleep"):
        yield


class TestAccumulation:
    def test_tokens_accumulate_across_calls(self):
        client = _client(_response(prompt=100, candidates=20, thoughts=5, cached=40),
                         _response(prompt=300, candidates=50, thoughts=0))
        gc.generate_with_retry(client=client, tag="t1", model="gemini-3.5-flash", contents="a")
        gc.generate_with_retry(client=client, tag="t1", model="gemini-3.5-flash", contents="b")

        totals = gc.get_usage_summary()["totals"]
        assert totals["calls"] == 2
        assert totals["failed_calls"] == 0
        assert totals["tokens"]["prompt"] == 400
        assert totals["tokens"]["cached"] == 40
        assert totals["tokens"]["candidates"] == 70
        assert totals["tokens"]["thoughts"] == 5
        assert totals["tokens"]["input"] == 400
        assert totals["tokens"]["output"] == 75

    def test_cost_counts_thinking_as_output(self):
        client = _client(_response(prompt=1_000_000, candidates=0, thoughts=1_000_000))
        gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
        summary = gc.get_usage_summary()
        # 1M input * $0.50 + 1M thinking (output) * $3.00
        assert summary["totals"]["estimated_cost_usd"] == pytest.approx(3.50)
        assert summary["by_model"]["gemini-3.5-flash"]["estimated_cost_usd"] == pytest.approx(3.50)

    def test_per_model_and_per_tag_split(self):
        client = _client(_response(prompt=10), _response(prompt=20), _response(prompt=40))
        gc.generate_with_retry(client=client, tag="phase5.7.toc", model="gemini-3.5-flash", contents="x")
        gc.generate_with_retry(client=client, tag="phase9.validator", model="gemini-3.6-flash", contents="x")
        gc.generate_with_retry(client=client, tag="phase9.validator", model="gemini-3.5-flash", contents="x")

        s = gc.get_usage_summary()
        assert s["by_model"]["gemini-3.5-flash"]["tokens"]["prompt"] == 50
        assert s["by_model"]["gemini-3.6-flash"]["tokens"]["prompt"] == 20
        assert s["by_tag"]["phase5.7.toc"]["calls"] == 1
        assert s["by_tag"]["phase9.validator"]["calls"] == 2
        assert s["by_tag"]["phase9.validator"]["tokens"]["prompt"] == 60

    def test_model_path_prefix_is_stripped(self):
        client = _client(_response())
        gc.generate_with_retry(client=client, tag="t",
                               model="publishers/google/models/gemini-3.5-flash", contents="x")
        assert list(gc.get_usage_summary()["by_model"]) == ["gemini-3.5-flash"]

    def test_default_tag_is_caller_module(self):
        client = _client(_response())
        gc.generate_with_retry(client=client, model="gemini-3.5-flash", contents="x")
        assert list(gc.get_usage_summary()["by_tag"]) == [__name__]

    def test_thread_safe_accumulation(self):
        n_threads, per_thread = 8, 50
        client = MagicMock()
        client.models.generate_content.side_effect = lambda **kw: _response(
            prompt=3, candidates=2, thoughts=1)

        def work():
            for _ in range(per_thread):
                gc.generate_with_retry(client=client, tag="threads",
                                       model="gemini-3.5-flash", contents="x")

        threads = [threading.Thread(target=work) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        totals = gc.get_usage_summary()["totals"]
        calls = n_threads * per_thread
        assert totals["calls"] == calls
        assert totals["tokens"]["prompt"] == 3 * calls
        assert totals["tokens"]["output"] == 3 * calls

    def test_retries_counted_and_tokens_of_rejected_attempts_kept(self, no_sleep):
        client = _client(Exception("429 RESOURCE_EXHAUSTED"),
                         _response(text="", prompt=50, candidates=0, thoughts=30),  # empty -> retried
                         _response(prompt=50, candidates=10, thoughts=0))
        gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
        totals = gc.get_usage_summary()["totals"]
        assert totals["calls"] == 1
        assert totals["retries"] == 2
        assert totals["tokens"]["prompt"] == 100
        assert totals["tokens"]["thoughts"] == 30

    def test_reset_usage(self):
        gc.generate_with_retry(client=_client(_response()), tag="t",
                               model="gemini-3.5-flash", contents="x")
        gc.reset_usage()
        s = gc.get_usage_summary()
        assert s["totals"]["calls"] == 0
        assert s["by_model"] == {} and s["by_tag"] == {}

    def test_mock_response_without_int_usage_is_safe(self):
        """Call sites mocked with MagicMock responses must not break accounting."""
        client = MagicMock()
        gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
        totals = gc.get_usage_summary()["totals"]
        assert totals["calls"] == 1
        assert totals["tokens"]["prompt"] == 0


class TestFailures:
    def test_non_transient_error_counted_as_failed(self):
        client = _client(ValueError("400 INVALID_ARGUMENT"))
        with pytest.raises(ValueError):
            gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
        totals = gc.get_usage_summary()["totals"]
        assert totals["calls"] == 1
        assert totals["failed_calls"] == 1
        assert totals["retries"] == 0

    def test_exhausted_retries_counted_as_failed(self, no_sleep):
        client = _client(*[Exception("503 UNAVAILABLE")] * 3)
        with pytest.raises(Exception, match="503"):
            gc.generate_with_retry(client=client, max_retries=2, tag="t",
                                   model="gemini-3.5-flash", contents="x")
        totals = gc.get_usage_summary()["totals"]
        assert totals["calls"] == 1
        assert totals["failed_calls"] == 1
        assert totals["retries"] == 2

    def test_max_tokens_failure_keeps_billed_tokens(self):
        client = _client(_response(text="", prompt=500, candidates=0, thoughts=1000,
                                   finish="FinishReason.MAX_TOKENS"))
        with pytest.raises(ValueError, match="MAX_TOKENS"):
            gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
        totals = gc.get_usage_summary()["totals"]
        assert totals["failed_calls"] == 1
        assert totals["tokens"]["thoughts"] == 1000
        assert totals["estimated_cost_usd"] == pytest.approx((500 * 0.5 + 1000 * 3.0) / 1e6)

    def test_record_usage_failed(self):
        gc.record_usage(None, "gemini-3.5-flash", "direct", success=False)
        assert gc.get_usage_summary()["by_tag"]["direct"]["failed_calls"] == 1


class TestUnknownModel:
    def test_unknown_model_cost_is_null_and_warns_once(self, caplog):
        client = _client(_response(), _response())
        with caplog.at_level(logging.WARNING, logger=gc.__name__):
            gc.generate_with_retry(client=client, tag="t", model="gemini-unpriced-test", contents="x")
            gc.generate_with_retry(client=client, tag="t", model="gemini-unpriced-test", contents="x")
            s = gc.get_usage_summary()

        warnings = [r for r in caplog.records
                    if r.levelno == logging.WARNING and "gemini-unpriced-test" in r.getMessage()]
        assert len(warnings) == 1
        assert s["by_model"]["gemini-unpriced-test"]["estimated_cost_usd"] is None
        assert s["by_model"]["gemini-unpriced-test"]["tokens"]["prompt"] == 200
        assert s["totals"]["estimated_cost_usd"] is None
        assert s["totals"]["unpriced_models"] == ["gemini-unpriced-test"]

    def test_mixed_group_cost_null_but_priced_part_reported(self):
        client = _client(_response(prompt=1_000_000, candidates=0, thoughts=0), _response())
        gc.generate_with_retry(client=client, tag="mix", model="gemini-3.5-flash", contents="x")
        gc.generate_with_retry(client=client, tag="mix", model="gemini-unpriced-test", contents="x")
        tag = gc.get_usage_summary()["by_tag"]["mix"]
        assert tag["estimated_cost_usd"] is None
        assert tag["estimated_cost_usd_priced_models"] == pytest.approx(0.50)


class TestSummaryOutput:
    def test_summary_json_shape(self, tmp_path):
        client = _client(_response(), _response())
        gc.generate_with_retry(client=client, tag="phase10a.summary", model="gemini-3.5-flash", contents="x")
        gc.generate_with_retry(client=client, tag="phase10b.visual.chart", model="gemini-3.8-flash", contents="x")

        out = tmp_path / "nested" / "gemini_usage.json"
        returned = gc.write_usage_summary(out)
        data = json.loads(out.read_text())

        assert set(data) == {"generated_at", "price_source", "prices_usd_per_1m",
                             "totals", "by_model", "by_tag", "by_model_tag"}
        assert data["by_model_tag"] == returned["by_model_tag"]
        group_keys = {"calls", "failed_calls", "retries", "latency_s", "tokens",
                      "estimated_cost_usd", "estimated_cost_usd_priced_models", "unpriced_models"}
        assert set(data["totals"]) == group_keys
        for group in [*data["by_model"].values(), *data["by_tag"].values()]:
            assert set(group) == group_keys
        assert set(data["totals"]["tokens"]) == {"prompt", "cached", "candidates", "thoughts",
                                                 "tool_use_prompt", "input", "output"}
        assert {(e["model"], e["tag"]) for e in data["by_model_tag"]} == {
            ("gemini-3.5-flash", "phase10a.summary"), ("gemini-3.8-flash", "phase10b.visual.chart")}
        assert data["prices_usd_per_1m"]["gemini-3.5-flash"] == [{"input": 0.5, "output": 3.0}]

    def test_merge_usage_from_worker_summary(self):
        gc.generate_with_retry(client=_client(_response(prompt=7)), tag="phase5.7.toc",
                               model="gemini-3.5-flash", contents="x")
        worker = gc.get_usage_summary()
        gc.merge_usage(worker)
        s = gc.get_usage_summary()
        assert s["totals"]["calls"] == 2
        assert s["totals"]["tokens"]["prompt"] == 14

    def test_log_usage_summary_info(self, caplog):
        gc.generate_with_retry(client=_client(_response()), tag="t",
                               model="gemini-3.5-flash", contents="x")
        with caplog.at_level(logging.INFO, logger=gc.__name__):
            gc.log_usage_summary()
        lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any(m.startswith("Gemini usage total: calls=1") for m in lines)

    def test_debug_line_per_call(self, caplog):
        client = _client(_response(), _response())
        with caplog.at_level(logging.DEBUG, logger=gc.__name__):
            gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
            gc.generate_with_retry(client=client, tag="t", model="gemini-3.5-flash", contents="x")
        debug = [r for r in caplog.records
                 if r.levelno == logging.DEBUG and r.getMessage().startswith("Gemini usage tag=t")]
        assert len(debug) == 2


class TestCallSiteTags:
    """Production call sites pass their phase tag through generate_with_retry."""

    def test_batch_service_tags_by_description(self):
        from src.batch_pipeline.batch_service import BatchService

        service = BatchService.__new__(BatchService)
        service.max_workers = 2
        service._trace_emitter = MagicMock()
        with patch("src.core.gemini_client.get_gemini_client", return_value=_client(_response())):
            service._process_batch_gemini(
                [{"prompt": "p", "model": "gemini-3.5-flash", "max_tokens": 10, "custom_id": "c1"}],
                "summary",
            )
        assert list(gc.get_usage_summary()["by_tag"]) == ["phase10a.summary"]

    def test_visual_extractor_tags_by_item_type(self):
        from google.genai import types

        from src.batch_pipeline.enrichment.gemini_visual_extractor import GeminiVisualExtractor

        extractor = GeminiVisualExtractor.__new__(GeminiVisualExtractor)
        with patch("src.core.gemini_client.get_gemini_client",
                   return_value=_client(_response(text='{"a": 1}'))):
            asyncio.run(extractor._generate_json(
                "chart", model="gemini-3.8-flash", contents="x",
                config=types.GenerateContentConfig(temperature=0)))
        s = gc.get_usage_summary()
        assert list(s["by_tag"]) == ["phase10b.visual.chart"]
        assert s["by_model"]["gemini-3.8-flash"]["estimated_cost_usd"] is not None


class TestDatedPrices:
    def test_flash_intro_then_standard_rate(self):
        from datetime import date
        from src.core.gemini_client import _price_for
        assert _price_for("gemini-3.8-flash", 0, date(2026, 12, 31)) == {"input": 0.75, "output": 3.75}
        assert _price_for("gemini-3.8-flash", 0, date(2027, 1, 1)) == {"input": 1.50, "output": 7.50}

    def test_pro_long_context_rate(self):
        from datetime import date
        from src.core.gemini_client import _cost_usd
        short = _cost_usd("gemini-3.1-pro-preview", {"prompt": 200_000, "candidates": 1_000_000}, date(2026, 10, 4))
        long = _cost_usd("gemini-3.1-pro-preview", {"prompt": 200_001, "candidates": 1_000_000}, date(2026, 10, 4))
        assert short == pytest.approx(0.4 + 12.0)
        assert long == pytest.approx(200_001 * 4.0 / 1e6 + 18.0)

    def test_cost_accumulates_per_call(self):
        from src.core import gemini_client as gc
        gc.reset_usage()
        gc._record("gemini-3.1-pro-preview", "t", {**gc._empty_tokens(), "prompt": 300_000})
        gc._record("gemini-3.1-pro-preview", "t", {**gc._empty_tokens(), "prompt": 100_000})
        total = gc.get_usage_summary()["totals"]["estimated_cost_usd"]
        assert total == pytest.approx((300_000 * 4.0 + 100_000 * 2.0) / 1e6)
        gc.reset_usage()
