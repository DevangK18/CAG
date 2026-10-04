"""Exit code and run summary rules for PipelineOrchestrator."""
import json
from types import SimpleNamespace

import pytest

from src.parsing_pipeline.main import (
    EXIT_NOTHING_SELECTED,
    EXIT_OK,
    EXIT_PARTIAL,
    PipelineOrchestrator,
    parse_skip_phases,
)


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
    assert orch._compute_exit_code() == EXIT_OK


def test_failed_report_is_partial(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    a, b = _complete(orch, "A", "B")
    orch.state.enrichment_complete = [a]
    orch.state.failed["enrichment"].append((b, "boom"))
    assert orch._compute_exit_code() == EXIT_PARTIAL
    statuses = {s["report_id"]: s for s in orch._report_statuses()}
    assert statuses["B"]["status"] == "failed" and statuses["B"]["phase"] == "enrichment"


def test_ocr_failure_counts(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    a, b = _complete(orch, "A", "B")
    for name in ("successful_triaged", "scaffold_complete", "layout_complete", "content_complete",
                 "chunking_complete", "assembly_complete", "enrichment_complete"):
        setattr(orch.state, name, [a])
    orch.state.failed["ocr"].append((b, "timeout"))
    assert orch._compute_exit_code() == EXIT_PARTIAL


def test_phase10_not_run_is_partial_unless_skipped(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A", phase10=False)
    assert orch._compute_exit_code() == EXIT_PARTIAL
    orch = _orch(tmp_path, monkeypatch, skip=["10a", "10b", "10c"])
    _complete(orch, "A", phase10=False)
    assert orch._compute_exit_code() == EXIT_OK


def test_nothing_selected(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    orch.state.tasks = []
    orch.fatal_error = "no reports selected"
    assert orch._compute_exit_code() == EXIT_NOTHING_SELECTED


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
    # The tier comes from where the old output was found
    entry = next(r for r in json.loads((out / "state" / "manifest.json").read_text())["reports"] if r["report_id"] == "X")
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


def test_exit_codes_avoid_python_reserved():
    assert {EXIT_PARTIAL, EXIT_NOTHING_SELECTED}.isdisjoint({1, 2})


def test_phase10_item_losses_are_partial(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A")
    orch.state.phase10_losses = {"10a": {"A": {"summary_variants": ["policy"]}}}
    assert orch._compute_exit_code() == EXIT_PARTIAL
    orch.exit_code = orch._compute_exit_code()
    data = json.loads(orch._write_run_summary().read_text())
    assert data["phase10_losses"]["10a"]["A"]["summary_variants"] == ["policy"]


def test_missing_requested_ids_are_partial(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A")
    orch.missing_report_ids = ["TYPO_2025_01"]
    assert orch._compute_exit_code() == EXIT_PARTIAL


def test_phase10a_losses_counted_from_summary_files(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A", "B")
    sums = tmp_path / "summaries"
    sums.mkdir()
    (sums / "A.json").write_text(json.dumps({"variants": {v: {} for v in
        ["executive", "journalist", "deep_dive", "simple"]}, "errors": [{"variant": "policy"}]}))
    (tmp_path / "A_ov.json").write_text("{}")
    service = SimpleNamespace(
        get_summary_output_path=lambda rid: sums / f"{rid}.json",
        get_overview_output_path=lambda rid: tmp_path / f"{rid}_ov.json",
        get_hierarchical_output_path=lambda rid: tmp_path / f"{rid}_hier.json",
    )
    orch._record_phase10a_losses(service, ["A", "B"], merge_failed=0)
    losses = orch.state.phase10_losses["10a"]
    assert losses["A"] == {"summary_variants": ["policy"]}
    assert losses["B"]["llm_overview"] is True and len(losses["B"]["summary_variants"]) == 5


def test_phase10b_losses_from_tracker(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    (tmp_path / "job1.json").write_text(json.dumps({"error_count": 4}))
    orch._record_phase10b_losses(SimpleNamespace(visual_extraction_dir=tmp_path), "job1")
    assert orch.state.phase10_losses["10b_items_failed"] == 4


def test_run_summary_lists_quarantined_files(tmp_path, monkeypatch):
    orch = _orch(tmp_path, monkeypatch)
    a, b = _complete(orch, "A", "B")
    orch.state.enrichment_complete = [a]
    orch.state.failed["enrichment"].append((b, "boom"))
    (tmp_path / "data/processed/state").mkdir(parents=True)
    (tmp_path / "data/processed/state/B_chunks.json").write_text("{}")
    orch._record_failures_in_manifest()
    orch.exit_code = orch._compute_exit_code()
    data = json.loads(orch._write_run_summary().read_text())
    assert data["quarantined_files"] == ["state/B_chunks.json"]

def test_lost_chapter_and_section_summaries_counted(tmp_path, monkeypatch):
    from src.batch_pipeline.prompts.summary_variants import VARIANTS
    orch = _orch(tmp_path, monkeypatch)
    _complete(orch, "A")
    (tmp_path / "A_sum.json").write_text(json.dumps({"variants": {v: {} for v in VARIANTS}}))
    (tmp_path / "A_ov.json").write_text("{}")
    (tmp_path / "A_hier.json").write_text(json.dumps({"stats": {"chapters_failed": 2, "sections_failed": 5}}))
    service = SimpleNamespace(
        get_summary_output_path=lambda rid: tmp_path / f"{rid}_sum.json",
        get_overview_output_path=lambda rid: tmp_path / f"{rid}_ov.json",
        get_hierarchical_output_path=lambda rid: tmp_path / f"{rid}_hier.json",
    )
    orch._record_phase10a_losses(service, ["A"], merge_failed=0)
    assert orch.state.phase10_losses["10a"]["A"] == {"chapter_summaries": 2, "section_summaries": 5}
    assert orch._compute_exit_code() == EXIT_PARTIAL


def test_phase10a_orchestration_runs_to_completion(tmp_path, monkeypatch):
    """Drives _phase_overview_summary with a fake BatchService (no Gemini calls)."""
    import src.batch_pipeline.batch_service as bs
    import src.batch_pipeline.process_results as pr
    from src.batch_pipeline.prompts.summary_variants import VARIANTS

    orch = _orch(tmp_path, monkeypatch)
    chunks = tmp_path / "A_chunks.json"
    chunks.write_text("{}")
    (task,) = _complete(orch, "A")
    task.assembled_output_path = str(chunks)

    class FakeService:
        def __init__(self, trace_emitter=None):
            pass

        def submit_overview_batch(self, files):
            return "gemini_sync_1"

        submit_summary_batch = submit_hierarchical_batch = submit_overview_batch

        def create_job_tracker(self, **kwargs):
            path = tmp_path / "tracker.json"
            path.write_text(json.dumps(kwargs))
            return path

        def get_summary_output_path(self, rid):
            path = tmp_path / f"{rid}_sum.json"
            path.write_text(json.dumps({"variants": {v: {} for v in VARIANTS}}))
            return path

        def get_overview_output_path(self, rid):
            path = tmp_path / f"{rid}_ov.json"
            path.write_text("{}")
            return path

        def get_hierarchical_output_path(self, rid):
            return tmp_path / "missing.json"

    monkeypatch.setattr(bs, "BatchService", FakeService)
    monkeypatch.setattr(pr, "build_final_overviews", lambda service, ids: (len(ids), 0))
    orch._phase_overview_summary()
    assert orch.state.phase10a_completed
    assert json.loads((tmp_path / "tracker.json").read_text())["status"] == "completed"
    assert orch.state.phase10_losses == {}
    assert orch._compute_exit_code() == EXIT_OK
