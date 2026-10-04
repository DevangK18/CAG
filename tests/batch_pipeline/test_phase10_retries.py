"""Phase 10 retries lost requests and never replaces a complete output with a partial one."""
import asyncio
import json

from src.batch_pipeline.batch_service import BatchService
from src.batch_pipeline.enrichment.gemini_visual_extractor import GeminiVisualExtractor


def _batch_service(tmp_path):
    svc = BatchService.__new__(BatchService)
    svc.summaries_dir = tmp_path
    svc.models = {}
    svc.max_workers = 4
    svc.retry_pause_s = 0
    svc._trace_emitter = type("E", (), {"emit_io": lambda *a: None, "emit_red_flag": lambda *a: None})()
    return svc


def test_transient_failures_get_a_second_pass(tmp_path, monkeypatch):
    svc = _batch_service(tmp_path)
    calls = {}

    def fake(prompt, model, max_tokens, custom_id, tag):
        calls[custom_id] = calls.get(custom_id, 0) + 1
        if custom_id == "b" and calls[custom_id] == 1:
            return {"custom_id": "b", "content": None, "error": "429 RESOURCE_EXHAUSTED"}
        if custom_id == "c":
            return {"custom_id": "c", "content": None, "error": "No text: max_output_tokens exhausted"}
        return {"custom_id": custom_id, "content": "ok", "error": None}

    monkeypatch.setattr(svc, "_process_single_gemini", fake)
    reqs = [{"custom_id": c, "prompt": "p", "model": "m", "max_tokens": 1} for c in "abc"]
    results = {r["custom_id"]: r for r in svc._process_batch_gemini(reqs, "summary")}
    assert results["b"]["error"] is None  # recovered on the second pass
    assert results["c"]["error"] and calls["c"] == 1  # not transient: not retried
    assert calls == {"a": 1, "b": 2, "c": 1}


def test_lost_variant_keeps_previous_text_marked_stale(tmp_path):
    svc = _batch_service(tmp_path)
    (tmp_path / "R_summaries.json").write_text(json.dumps({"variants": {
        "executive": {"content": "old exec"}, "simple": {"content": "old simple"}}}))
    svc._save_summary_results(
        [{"custom_id": "a", "content": "new exec", "error": None},
         {"custom_id": "b", "content": None, "error": "429"}],
        {"a": {"report_id": "R", "variant": "executive"}, "b": {"report_id": "R", "variant": "simple"}},
    )
    data = json.loads((tmp_path / "R_summaries.json").read_text())
    assert data["variants"]["executive"]["content"] == "new exec"
    assert data["variants"]["simple"] == {"content": "old simple", "stale": True}
    assert data["stale_variants"] == ["simple"]


def test_single_element_list_is_unwrapped():
    ext = GeminiVisualExtractor.__new__(GeminiVisualExtractor)
    result = ext._parse_json_response('[{"title": "Chart", "series": []}]', "chart")
    assert result["success"] and result["title"] == "Chart"


def test_visual_items_run_concurrently_in_order_and_failures_retry(monkeypatch):
    ext = GeminiVisualExtractor.__new__(GeminiVisualExtractor)
    ext._trace_emitter = None
    ext.retry_pause_s = 0
    attempts, running, peak = {}, [0], [0]

    async def fake_chart(path, context=""):
        attempts[path] = attempts.get(path, 0) + 1
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        await asyncio.sleep(0.01)
        running[0] -= 1
        if path == "c2" and attempts[path] == 1:
            return {"success": False, "error": "JSON parse error: truncated"}
        return {"success": True, "path": path}

    monkeypatch.setattr(ext, "extract_chart", fake_chart)
    items = [{"type": "chart", "image_path": f"c{i}", "chunk_id": f"k{i}"} for i in range(6)]
    results = asyncio.run(ext.process_batch(items))
    assert [r["path"] for r in results] == [f"c{i}" for i in range(6)]
    assert all(r["success"] for r in results) and attempts["c2"] == 2
    assert peak[0] > 1
