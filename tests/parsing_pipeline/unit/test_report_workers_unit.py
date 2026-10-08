"""--workers: per-report work runs the same function in this process or in worker processes."""
from types import SimpleNamespace

import pytest

from src.parsing_pipeline import report_workers
from src.parsing_pipeline.instrumentation import TraceEmitter
from src.parsing_pipeline.main import PipelineOrchestrator
from src.parsing_pipeline.modules.assembly_service import AssemblyService
from src.parsing_pipeline.modules.enrichment.entity_extractor import EntityExtractor
from tests.parsing_pipeline.unit import _worker_fns


def _orch(tmp_path, monkeypatch, workers=1, trace=False):
    monkeypatch.chdir(tmp_path)
    orch = PipelineOrchestrator(manifest_path="m.xlsx", quiet=True, run_id="t1", workers=workers, trace=trace)
    if not trace:
        # The shared no-op emitter keeps red flags across orchestrators in one process
        orch.state.trace_emitter = TraceEmitter(enabled=False)
    return orch


def _tasks(*ids):
    return [SimpleNamespace(report_id=i) for i in ids]


def test_one_worker_runs_in_process_when_asked(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    calls = []

    def fn(task, emitter, suffix):
        calls.append(task.report_id)
        assert emitter is orch.state.trace_emitter
        return task.report_id + suffix

    results = orch._per_report("6", fn, _tasks("A", "B"), args_for=lambda t: ("!",))
    assert calls == []  # nothing runs until the phase loop asks
    assert [r.get() for _, r in results] == ["A!", "B!"]
    assert calls == ["A", "B"]


def test_in_process_errors_propagate_unchanged(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    (_, ok), (_, bad) = orch._per_report("6", _worker_fns.fail_on_b, _tasks("A", "B"))
    assert ok.get() == "A"
    with pytest.raises(ValueError, match="boom on B"):
        bad.get()


def test_trace_keeps_the_run_sequential(tmp_path, monkeypatch):
    assert _orch(tmp_path, monkeypatch, workers=4, trace=True).workers == 1


def test_workers_keep_order_return_errors_and_red_flags(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch, workers=2)
    try:
        tasks = _tasks("A", "B", "C")
        results = orch._per_report("6", _worker_fns.tag_report, tasks, args_for=lambda t: ("-x",))
        assert [t.report_id for t, _ in results] == ["A", "B", "C"]
        assert [r.get() for _, r in results] == ["A-x", "B-x", "C-x"]
        # The worker's red flag is recorded for its report in the run's emitter
        assert [f["flag"] for f in orch.state.trace_emitter.get_red_flags("B")] == ["test flag"]

        (_, ok), (_, bad) = orch._per_report("6", _worker_fns.fail_on_b, _tasks("A", "B"))
        assert ok.get() == "A"
        with pytest.raises(report_workers.WorkerError, match="boom on B"):
            bad.get()
    finally:
        orch._close_pool()


def test_worker_sees_the_reports_earlier_red_flags(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch, workers=2)
    try:
        orch.state.trace_emitter.emit_red_flag("4", "earlier", {"report_id": "A"})
        results = orch._per_report("6", _worker_fns.prior_flag_count, _tasks("A", "B"))
        assert [r.get() for _, r in results] == [1, 0]
        # Seeded flags are not sent back as new ones
        assert len(orch.state.trace_emitter.get_red_flags("A")) == 1
    finally:
        orch._close_pool()


def test_run_in_worker_returns_only_new_flags_and_error_text():
    task = SimpleNamespace(report_id="R")
    prior = [{"phase": "4", "flag": "old", "details": {}}]
    result = report_workers.run_in_worker(_worker_fns.tag_report, task, ("?",), prior)
    assert result.value == "R?" and result.error is None
    assert [f["flag"] for f in result.red_flags] == ["test flag"]

    failed = report_workers.run_in_worker(_worker_fns.fail_on_b, SimpleNamespace(report_id="B"), ())
    assert failed.value is None and failed.error == "boom on B"


def test_add_red_flags_appends_per_report():
    emitter = TraceEmitter(enabled=False)
    emitter.add_red_flags("R", [{"phase": "6", "flag": "x", "details": {}}])
    emitter.add_red_flags("R", [])
    assert [f["flag"] for f in emitter.get_red_flags("R")] == ["x"]


def test_mark_assembled_records_the_working_file(tmp_path):
    svc = AssemblyService(output_dir=str(tmp_path), run_id="r1")
    working = tmp_path / "union" / "U_chunks.json.working"
    entry = svc.mark_assembled("U", "union", working, parent_chunks=3, child_chunks=9)
    assert entry["status"] == "assembled"
    assert entry["output_path"] == "union/U_chunks.json"
    assert (entry["parent_chunks"], entry["child_chunks"]) == (3, 9)


def test_entities_keep_the_first_ten_in_text_order():
    # A set used to decide both the order and which ten were kept, differently per process
    names = ["Finance", "Railways", "Defence", "Education", "Home Affairs", "External Affairs",
             "Coal", "Power", "Textiles", "Steel", "Mines", "Tourism"]
    text = ". ".join(f"The Ministry of {n} replied" for n in names)
    assert EntityExtractor().extract_entities_from_text(text) == [f"Ministry of {n}" for n in names[:10]]


def test_report_and_phase_times_reach_the_run_summary(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch, workers=2)
    try:
        with orch._timed("6"):
            results = orch._per_report("6", _worker_fns.tag_report, _tasks("A", "B"), args_for=lambda t: ("",))
            [r.get() for _, r in results]
    finally:
        orch._close_pool()
    timing = orch._timing_summary()
    assert timing["workers"] == 2
    assert set(timing["report_seconds"]) == {"A", "B"}
    assert "6" in timing["report_seconds"]["A"] and timing["phase_seconds"]["6"] >= 0


def _layout_tasks(tmp_path, *ids):
    return [SimpleNamespace(report_id=i, marker_dir=str(tmp_path), processing_status="scaffold_complete",
                            error_log=[], layout=None) for i in ids]


def test_docling_crash_is_retried_in_a_new_process(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    orch._docling_fn = _worker_fns.crash_first_time
    orch.state.scaffold_complete = _layout_tasks(tmp_path, "A", "B")
    orch._phase_layout()
    assert [t.report_id for t in orch.state.layout_complete] == ["A", "B"]
    assert orch._docling_pool is None  # closed after the phase


def test_docling_crashing_twice_fails_only_that_report(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    orch._docling_fn = _worker_fns.crash_always
    orch.state.scaffold_complete = _layout_tasks(tmp_path, "A")
    orch._phase_layout()
    assert orch.state.layout_complete == []
    (task, error), = orch.state.failed["layout_analysis"]
    assert task.report_id == "A" and "crashed twice" in error
    assert [f["flag"] for f in orch.state.trace_emitter.get_red_flags("A")] == ["Docling process crashed"]


def test_hung_docling_conversion_is_killed_and_the_next_report_converts(tmp_path, monkeypatch):
    import time

    from src.parsing_pipeline.config import get_config

    monkeypatch.setattr(get_config().layout, "conversion_timeout", 2)
    monkeypatch.setattr(get_config().layout, "conversion_timeout_per_page", 0)
    orch = _orch(tmp_path, monkeypatch)
    monkeypatch.setattr(type(orch), "DOCLING_KILL_GRACE_S", 3)
    orch._docling_fn = _worker_fns.hang_on_a
    orch.state.scaffold_complete = _layout_tasks(tmp_path, "A", "B")
    started = time.monotonic()
    orch._phase_layout()
    # Killed within the limit plus the grace period (plus process start-up), not after an hour
    assert time.monotonic() - started < 2 + 3 + 30
    assert [t.report_id for t in orch.state.layout_complete] == ["B"]
    (task, error), = orch.state.failed["layout_analysis"]
    assert task.report_id == "A" and "killed and restarted" in error
