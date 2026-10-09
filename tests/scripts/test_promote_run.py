"""Promoting a test run: dry run changes nothing; apply quarantines replaced files and merges manifests."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "promote_run", Path(__file__).resolve().parents[2] / "scripts/pipeline/promote_run.py")
promote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promote)

B = "gs://bkt/"


class FakeBucket:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.calls = []

    def __call__(self, cmd, *args):
        self.calls.append((cmd, *args))
        if cmd == "ls":
            prefix = args[-1]
            return "\n".join(k for k in sorted(self.objects) if k.startswith(prefix))
        if cmd == "cat":
            if args[0] not in self.objects:
                raise RuntimeError("matched no objects")
            return self.objects[args[0]]
        if cmd == "cp":
            src = args[0]
            self.objects[args[1]] = Path(src).read_text() if not src.startswith("gs://") else self.objects[src]
        if cmd == "mv":
            self.objects[args[1]] = self.objects.pop(args[0])
        return ""


def manifest(*ids, status="completed"):
    return json.dumps({"corpus_version": "2.0", "reports": [{"report_id": i, "status": status} for i in ids]})


def bucket():
    return FakeBucket({
        f"{B}run1/processed/union/manifest.json": manifest("A", "B"),
        f"{B}run1/processed/union/A_chunks.json": "new A",
        f"{B}run1/processed/union/B_chunks.json": "new B",
        f"{B}run1/processed/union/B_chunks.json.stale": "old",
        f"{B}run1/batch_jobs/summaries/A_summaries.json": "new A sum",
        f"{B}processed/union/manifest.json": manifest("A", "C"),
        f"{B}processed/union/A_chunks.json": "old A",
        f"{B}processed/union/C_chunks.json": "old C",
    })


def test_dry_run_changes_nothing(capsys):
    fake = bucket()
    before = dict(fake.objects)
    assert promote.main(["--bucket", "bkt", "--prefix", "run1", "--tier", "union"], run=fake) == 0
    assert fake.objects == before
    out = capsys.readouterr().out
    assert "replace  processed/union/A_chunks.json" in out and "new      processed/union/B_chunks.json" in out
    assert ".stale" not in out


def test_apply_quarantines_and_merges():
    fake = bucket()
    promote.main(["--bucket", "bkt", "--prefix", "run1", "--tier", "union", "--apply", "--run-id", "9"], run=fake)
    o = fake.objects
    assert o[f"{B}processed/union/A_chunks.json"] == "new A"
    assert o[f"{B}quarantine/promote-9/processed/union/A_chunks.json"] == "old A"
    assert o[f"{B}processed/union/B_chunks.json"] == "new B" and o[f"{B}processed/union/C_chunks.json"] == "old C"
    assert o[f"{B}batch_jobs/summaries/A_summaries.json"] == "new A sum"
    merged = json.loads(o[f"{B}processed/union/manifest.json"])
    assert [r["report_id"] for r in merged["reports"]] == ["A", "B", "C"]
    assert f"{B}quarantine/promote-9/processed/union/manifest.json" in o


def test_production_prefix_refused():
    assert promote.main(["--bucket", "bkt", "--prefix", "processed", "--tier", "union"], run=bucket()) == 2
