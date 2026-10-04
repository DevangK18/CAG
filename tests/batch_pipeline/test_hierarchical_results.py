"""Failed chapter/section summary requests are recorded per report."""
import json

from src.batch_pipeline.batch_service import BatchService


def test_failed_hierarchical_requests_recorded(tmp_path):
    svc = BatchService.__new__(BatchService)
    svc.batch_jobs_dir = tmp_path
    results = [
        {"custom_id": "c1", "content": "chapter text", "error": None},
        {"custom_id": "c2", "content": None, "error": "429 RESOURCE_EXHAUSTED"},
        {"custom_id": "s1", "content": None, "error": "timeout"},
    ]
    mapping = {
        "c1": {"report_id": "R", "level": 2, "parent_chunk_id": "p1", "title": "Ch 1"},
        "c2": {"report_id": "R", "level": 2, "parent_chunk_id": "p2", "title": "Ch 2"},
        "s1": {"report_id": "R", "level": 1, "parent_chunk_id": "p3", "title": "1.1"},
    }
    stats = svc._save_hierarchical_results(results, mapping)
    data = json.loads((tmp_path / "hierarchical" / "R_hierarchical.json").read_text())
    assert stats["error_count"] == 2
    assert data["stats"]["chapters_failed"] == 1 and data["stats"]["sections_failed"] == 1
    assert [e["parent_chunk_id"] for e in data["errors"]] == ["p2", "p3"]
