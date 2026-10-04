"""The indexer only picks up reports the manifest lists as completed."""
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


def test_skips_failed_and_unknown_reports(tmp_path):
    files = _files(tmp_path, "A", "B", "C")
    (tmp_path / "manifest.json").write_text(json.dumps({"reports": [
        {"report_id": "A", "status": "completed"},
        {"report_id": "B", "status": "failed"},
    ]}))
    kept = Indexer._drop_unfinished_reports(files, tmp_path)
    assert [p.name for p in kept] == ["A_chunks.json"]


def test_without_manifest_keeps_everything(tmp_path):
    files = _files(tmp_path, "A", "B")
    assert Indexer._drop_unfinished_reports(files, tmp_path) == files
