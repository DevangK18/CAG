"""Exit code and run summary rules for PipelineOrchestrator."""
import json
from types import SimpleNamespace

import pytest

from src.parsing_pipeline.main import PipelineOrchestrator, parse_skip_phases


def _orch(tmp_path, monkeypatch, skip=()):
    monkeypatch.chdir(tmp_path)
    return PipelineOrchestrator(manifest_path="m.xlsx", skip_phases=list(skip), quiet=True, run_id="t1")


def _complete(orch, *ids, phase10=True):
    tasks = [SimpleNamespace(report_id=i) for i in ids]
    orch.state.tasks = tasks
    for name in ("successful_triaged", "scaffold_complete", "layout_complete", "content_complete",
                 "chunking_complete", "assembly_complete", "enrichment_complete"):
        setattr(orch.state, name, list(tasks))
    orch.state.phase10a_completed = orch.state.phase10b_completed = orch.state.phase10c_completed = phase10
    return tasks


def test_all_completed_is_zero(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A", "B")
    assert orch._compute_exit_code() == 0


def test_failed_report_is_one(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    a, b = _complete(orch, "A", "B")
    orch.state.enrichment_complete = [a]
    orch.state.failed["enrichment"].append((b, "boom"))
    assert orch._compute_exit_code() == 1
    statuses = {s["report_id"]: s for s in orch._report_statuses()}
    assert statuses["B"]["status"] == "failed" and statuses["B"]["phase"] == "enrichment"


def test_ocr_failure_counts(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    a, b = _complete(orch, "A", "B")
    for name in ("successful_triaged", "scaffold_complete", "layout_complete", "content_complete",
                 "chunking_complete", "assembly_complete", "enrichment_complete"):
        setattr(orch.state, name, [a])
    orch.state.failed["ocr"].append((b, "timeout"))
    assert orch._compute_exit_code() == 1


def test_phase10_not_run_is_one_unless_skipped(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A", phase10=False)
    assert orch._compute_exit_code() == 1
    orch = _orch(tmp_path, monkeypatch, skip=["10a", "10b", "10c"])
    _complete(orch, "A", phase10=False)
    assert orch._compute_exit_code() == 0


def test_nothing_selected_is_two(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    orch.state.tasks = []
    orch.fatal_error = "no reports selected"
    assert orch._compute_exit_code() == 2


def test_run_summary_written(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A")
    orch.exit_code = orch._compute_exit_code()
    path = orch._write_run_summary()
    data = json.loads(path.read_text())
    assert path.name == "run_summary_t1.json"
    assert data["exit_code"] == 0 and data["reports"]["completed"] == 1
    assert data["phase10"] == {"10a": "completed", "10b": "completed", "10c": "completed"}


@pytest.mark.parametrize("raw,expected", [(["10a,10b"], ["10a", "10b"]), (["5.5", "10c"], ["5.5", "10c"]), ([], [])])
def test_parse_skip_phases(raw, expected):
    assert parse_skip_phases(raw) == expected


def test_parse_skip_phases_rejects_unknown():
    with pytest.raises(ValueError):
        parse_skip_phases(["10a,11"])


def test_mark_failed_quarantines_old_output(tmp_path):
    from src.parsing_pipeline.modules.assembly_service import AssemblyService
    out = tmp_path / "processed"
    (out / "state").mkdir(parents=True)
    (out / "state" / "X_chunks.json").write_text("{}")
    (out / "state" / "X_overview.json").write_text("{}")
    svc = AssemblyService(output_dir=str(out))
    svc.mark_failed("X", "ocr", "timeout")
    assert not (out / "state" / "X_chunks.json").exists()
    assert (out / "state" / "X_chunks.json.stale").exists()
    entry = next(r for r in json.loads((out / "manifest.json").read_text())["reports"] if r["report_id"] == "X")
    assert entry["status"] == "failed" and entry["stale_output"] is True
    assert sorted(entry["quarantined_files"]) == ["state/X_chunks.json.stale", "state/X_overview.json.stale"]


def test_red_flags_kept_when_tracing_off():
    from src.parsing_pipeline.instrumentation.trace_emitter import TraceEmitter
    emitter = TraceEmitter(enabled=False)
    emitter.set_current_report("R1")
    emitter.emit_red_flag("9", "monetary_total_implausible", {"total_crore": 1e9})
    emitter.emit_red_flag("3", "ocr_failed", {"report_id": "R2", "error": ValueError("x")})
    assert emitter.get_red_flags("R1")[0]["flag"] == "monetary_total_implausible"
    assert emitter.get_red_flags("R2")[0]["details"]["error"] == "x"
    assert set(emitter.get_red_flags()) == {"R1", "R2"}
