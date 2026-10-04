"""Phase 8 working file, per-tier manifests and report status."""
import json

from src.core.data_contracts import ChildChunk, DocumentTask, ParentChunk
from src.core.processed_manifest import load_report_entries
from src.parsing_pipeline.main import PipelineOrchestrator
from src.parsing_pipeline.modules.assembly_service import AssemblyService


def _task(report_id, tier):
    return DocumentTask(
        report_id=report_id,
        source_url="http://example.com/x.pdf",
        initial_metadata={"government_body_type": tier},
        local_pdf_path="/fake/x.pdf",
    )


def _chunks():
    parent = ParentChunk(
        chunk_id="p1", report_id="R", hierarchy={"level_1": "Chapter 1"},
        page_range_physical=(0, 2), page_range_logical=("1", "3"), toc_entry="Chapter 1", toc_level=1,
    )
    child = ChildChunk(
        chunk_id="c1", parent_chunk_id="p1", content_type="paragraph", content="Text",
        source_page_physical=0, source_bbox=[0.0, 0.0, 100.0, 100.0], model_used="test",
        layout_label="Text", report_id="R", report_title="T", report_no="1 of 2024",
        hierarchy={"level_1": "Chapter 1"}, source_filename="x.pdf",
    )
    return [parent], [child]


def _tier_manifest(out, tier):
    return {r["report_id"]: r for r in json.loads((out / tier / "manifest.json").read_text())["reports"]}


def test_phase8_writes_working_file_and_assembled_status(tmp_path):
    svc = AssemblyService(output_dir=str(tmp_path), run_id="r1")
    path = svc.assemble_document(_task("R", "state"), *_chunks())

    assert path.endswith("state/R_chunks.json.working")
    assert not (tmp_path / "state" / "R_chunks.json").exists()
    data = json.loads((tmp_path / "state" / "R_chunks.json.working").read_text())
    assert data["report_metadata"]["processing_status"] == "assembled"

    entry = _tier_manifest(tmp_path, "state")["R"]
    assert entry["status"] == "assembled"
    assert entry["output_path"] == "state/R_chunks.json"
    assert entry["run_id"] == "r1" and entry["government_body_type"] == "state"
    assert not (tmp_path / "manifest.json").exists()


def test_completed_only_after_phase9(tmp_path):
    svc = AssemblyService(output_dir=str(tmp_path), run_id="r1")
    working = svc.assemble_document(_task("R", "union"), *_chunks())
    final = AssemblyService.final_output_path(working)
    assert final.name == "R_chunks.json"

    svc.mark_completed("R", "union", final, parent_chunks=1, child_chunks=1)
    manifest = json.loads((tmp_path / "union" / "manifest.json").read_text())
    assert manifest["completed_reports"] == 1 and manifest["total_child_chunks"] == 1
    assert _tier_manifest(tmp_path, "union")["R"]["status"] == "completed"


def test_tiers_do_not_overwrite_each_other(tmp_path):
    AssemblyService(output_dir=str(tmp_path)).mark_completed("U", "union", tmp_path / "union" / "U_chunks.json")
    AssemblyService(output_dir=str(tmp_path)).mark_completed("S", "state", tmp_path / "state" / "S_chunks.json")
    entries = load_report_entries(tmp_path)
    assert entries["U"]["status"] == entries["S"]["status"] == "completed"


def test_failure_clears_completed_and_keeps_tier(tmp_path):
    svc = AssemblyService(output_dir=str(tmp_path))
    svc.mark_completed("R", "local_body", tmp_path / "local_body" / "R_chunks.json")
    (tmp_path / "local_body" / "R_chunks.json").write_text("{}")

    moved = AssemblyService(output_dir=str(tmp_path)).mark_failed("R", "enrichment", "boom")
    assert moved == ["local_body/R_chunks.json.stale"]
    entry = _tier_manifest(tmp_path, "local_body")["R"]
    assert entry["status"] == "failed" and entry["stale_output"] is True


def test_phases_completed_respects_skip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orch = PipelineOrchestrator(manifest_path="m.xlsx", skip_phases=["5.5"], quiet=True, run_id="t")
    assert "5.5" not in orch._phases_completed()
    assert orch._phases_completed()[-1] == "9"
