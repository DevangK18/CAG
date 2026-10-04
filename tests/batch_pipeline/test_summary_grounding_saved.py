"""Summary variants carry a number-grounding check against the report."""
import json

from src.batch_pipeline.batch_service import BatchService
from src.batch_pipeline.grounding import source_numbers


def _service(tmp_path):
    svc = BatchService.__new__(BatchService)
    svc.summaries_dir = tmp_path
    svc.models = {"executive": "m", "simple": "m"}
    return svc


def test_grounding_stored_per_variant(tmp_path):
    svc = _service(tmp_path)
    known = {"R": source_numbers("Excess expenditure of ₹1,234.56 crore in 2022-23 across 47 districts.")}
    results = [
        {"custom_id": "a", "content": "Excess spending of ₹1,234.56 crore over 47 districts.", "error": None},
        {"custom_id": "b", "content": "₹12,000 crore lost in 2,400 schools and 60% of 315 blocks.", "error": None},
    ]
    mapping = {"a": {"report_id": "R", "variant": "executive"}, "b": {"report_id": "R", "variant": "simple"}}
    svc._save_summary_results(results, mapping, known)

    data = json.loads((tmp_path / "R_summaries.json").read_text())
    assert data["variants"]["executive"]["grounding"]["grounded"] is True
    assert data["variants"]["simple"]["grounding"]["grounded"] is False
    assert data["ungrounded_variants"] == ["simple"]


def test_without_sources_no_grounding_field(tmp_path):
    svc = _service(tmp_path)
    svc._save_summary_results(
        [{"custom_id": "a", "content": "Text 123", "error": None}],
        {"a": {"report_id": "R", "variant": "executive"}},
    )
    data = json.loads((tmp_path / "R_summaries.json").read_text())
    assert "grounding" not in data["variants"]["executive"] and data["ungrounded_variants"] == []
