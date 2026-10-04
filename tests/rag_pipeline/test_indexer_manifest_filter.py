"""The indexer skips reports the processed manifests mark as failed."""
import json

from src.rag_pipeline.indexer import Indexer


def _files(root, *ids):
    tier = root / "union"
    tier.mkdir(parents=True, exist_ok=True)
    paths = []
    for rid in ids:
        p = tier / f"{rid}_chunks.json"
        p.write_text("{}")
        paths.append(p)
    return paths


def test_skips_failed_keeps_unlisted(tmp_path, caplog):
    files = _files(tmp_path, "A", "B", "C")
    (tmp_path / "manifest.json").write_text(json.dumps({"reports": [
        {"report_id": "A", "status": "completed"},
        {"report_id": "B", "status": "failed"},
    ]}))
    kept = Indexer._drop_failed_reports(files, tmp_path)
    assert [p.name for p in kept] == ["A_chunks.json", "C_chunks.json"]
    assert "no manifest entry" in caplog.text and "'C'" in caplog.text


def test_without_manifest_keeps_everything(tmp_path):
    files = _files(tmp_path, "A", "B")
    assert Indexer._drop_failed_reports(files, tmp_path) == files


def test_tier_manifest_wins_over_legacy(tmp_path):
    files = _files(tmp_path, "A", "B")
    (tmp_path / "manifest.json").write_text(json.dumps({"reports": [
        {"report_id": "A", "status": "completed"},
        {"report_id": "B", "status": "completed"},
    ]}))
    (tmp_path / "union" / "manifest.json").write_text(json.dumps({"reports": [
        {"report_id": "B", "status": "failed"},
    ]}))
    # Same result whether indexing data/processed or data/processed/union
    for root in (tmp_path, tmp_path / "union"):
        assert [p.name for p in Indexer._drop_failed_reports(files, root)] == ["A_chunks.json"]
