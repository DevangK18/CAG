"""Promote a test run's output to the production paths of the data bucket.

  python scripts/pipeline/promote_run.py --bucket cag-data-443e4a28 --prefix pr09-final-20261010 \
      --tier union [--apply] [--run-id 12345]

Without --apply it only prints what would change. With --apply, for every file of the
run's reports in the tier:
- the production file it replaces is moved to quarantine/promote-<run_id>/<same path>;
- the run's file is copied in.
The tier manifest is merged: the run's entries replace production's for the same
reports; production entries for other reports stay.

A report is promoted when the run's tier manifest marks it completed. Its files are
those under processed/<tier>/, batch_jobs/{overviews,summaries,hierarchical,
visual_extraction}/ and extraction_images/ whose name contains the report ID.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

TIERS = ("union", "state", "local_body")
AREAS = (
    "processed/{tier}/",
    "batch_jobs/overviews/",
    "batch_jobs/summaries/",
    "batch_jobs/hierarchical/",
    "batch_jobs/visual_extraction/",
    "extraction_images/",
)
PRODUCTION_NAMES = {
    "raw", "processed", "batch_jobs", "manifests", "runs", "runs-gpu", "logs",
    "extraction_images", "entity_graph", "canonical", "traces", "quarantine",
}


@dataclass
class Change:
    action: str  # new, replace
    path: str  # path relative to the bucket root (production) and to the prefix (run)


def gcloud(*args: str) -> str:
    out = subprocess.run(["gcloud", "storage", *args], capture_output=True, text=True)
    if out.returncode != 0 and "matched no objects" not in out.stderr and "One or more URLs matched no objects" not in out.stderr:
        raise RuntimeError(f"gcloud storage {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


def list_objects(url: str, run: Callable = gcloud) -> List[str]:
    return [line.strip() for line in run("ls", "-r", url).splitlines() if line.strip() and not line.endswith(":")]


def completed_reports(manifest: dict) -> List[str]:
    return [r["report_id"] for r in manifest.get("reports", []) if r.get("status") == "completed"]


def plan(run_paths: Iterable[str], production_paths: Iterable[str], report_ids: List[str], tier: str) -> List[Change]:
    """Changes to make, from paths relative to the run prefix and to the bucket root."""
    areas = [a.format(tier=tier) for a in AREAS]
    production = set(production_paths)
    changes = []
    for path in sorted(run_paths):
        if not any(path.startswith(area) for area in areas):
            continue
        name = path.rsplit("/", 1)[-1]
        if path == f"processed/{tier}/manifest.json":
            continue  # merged, not copied
        if not any(rid in path for rid in report_ids):
            continue
        if name.endswith((".stale", ".working")):
            continue
        changes.append(Change("replace" if path in production else "new", path))
    return changes


def merge_manifest(production: Optional[dict], run: dict) -> dict:
    """Run entries replace production's for the same report; other production entries stay."""
    merged = dict(production or {k: v for k, v in run.items() if k != "reports"})
    by_id = {r["report_id"]: r for r in (production or {}).get("reports", [])}
    for entry in run.get("reports", []):
        if entry.get("status") == "completed":
            by_id[entry["report_id"]] = entry
    merged["reports"] = sorted(by_id.values(), key=lambda r: r["report_id"])
    return merged


def relative(urls: Iterable[str], root: str) -> List[str]:
    return [u[len(root):] for u in urls if u.startswith(root)]


def main(argv=None, run: Callable = gcloud) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--tier", required=True, choices=TIERS + ("all",))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--run-id", default="manual")
    a = ap.parse_args(argv)
    if a.prefix in PRODUCTION_NAMES or "/" in a.prefix or not a.prefix:
        print(f"ERROR: '{a.prefix}' is not a test prefix")
        return 2

    bucket = f"gs://{a.bucket}/"
    run_root = f"{bucket}{a.prefix}/"
    quarantine = f"{bucket}quarantine/promote-{a.run_id}/"
    total = 0
    for tier in TIERS if a.tier == "all" else (a.tier,):
        manifest_url = f"{run_root}processed/{tier}/manifest.json"
        try:
            run_manifest = json.loads(run("cat", manifest_url))
        except (RuntimeError, ValueError):
            print(f"{tier}: no manifest in the run ({manifest_url}); nothing to promote")
            continue
        report_ids = completed_reports(run_manifest)
        run_paths = relative(list_objects(run_root, run), run_root)
        production_paths = []
        for area in AREAS:
            area = area.format(tier=tier)
            production_paths += relative(list_objects(f"{bucket}{area}", run), bucket)
        changes = plan(run_paths, production_paths, report_ids, tier)
        counts = {k: sum(c.action == k for c in changes) for k in ("new", "replace")}
        print(f"{tier}: {len(report_ids)} completed reports; {counts['new']} new files, "
              f"{counts['replace']} replaced (production copy to {quarantine}); manifest merged")
        for c in changes:
            print(f"  {c.action:8} {c.path}")
        total += len(changes)
        if not a.apply:
            continue
        for c in changes:
            if c.action == "replace":
                run("mv", f"{bucket}{c.path}", f"{quarantine}{c.path}")
            run("cp", f"{run_root}{c.path}", f"{bucket}{c.path}")
        production_manifest_url = f"{bucket}processed/{tier}/manifest.json"
        try:
            production_manifest = json.loads(run("cat", production_manifest_url))
            run("cp", production_manifest_url, f"{quarantine}processed/{tier}/manifest.json")
        except (RuntimeError, ValueError):
            production_manifest = None
        merged = merge_manifest(production_manifest, run_manifest)
        tmp = f"/tmp/promote_manifest_{tier}.json"
        with open(tmp, "w") as f:
            json.dump(merged, f, indent=2)
        run("cp", tmp, production_manifest_url)
    print(f"{'Applied' if a.apply else 'Dry run'}: {total} file changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
