#!/usr/bin/env python3
"""
Pre-flight check: compare parsing pipeline output against the source PDFs
==========================================================================

Run on a few reports locally before launching a full VM run. The checks live in
src/parsing_pipeline/quality/preflight.py (the pipeline runs the same checks on
every report after Phase 9); this script is the command-line front end.

Usage:
    python scripts/evaluation/preflight_check.py \\
        --processed-dir data/processed/union --pdf-dir data/raw/union \\
        --reports 2025_04 2023_19 --json-out preflight.json

Exit code 1 if any check fails.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.parsing_pipeline.quality.preflight import THRESHOLDS, check_report, default_max_chunk_chars  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--processed-dir", default="data/processed/union")
    parser.add_argument("--pdf-dir", default="data/raw/union")
    parser.add_argument("--reports", nargs="*", help="Report id prefixes (e.g. 2025_04); default all")
    parser.add_argument("--json-out", help="Write full results as JSON")
    args = parser.parse_args()

    max_chunk_chars = default_max_chunk_chars()
    results = []
    for chunks_path in sorted(Path(args.processed_dir).glob("*_chunks.json")):
        report_id = chunks_path.name[: -len("_chunks.json")]
        if args.reports and not any(report_id.startswith(r) for r in args.reports):
            continue
        pdf_path = Path(args.pdf_dir) / f"{report_id}.pdf"
        if not pdf_path.exists():
            print(f"skip {report_id}: no PDF at {pdf_path}")
            continue
        result = check_report(json.loads(chunks_path.read_text()), pdf_path, max_chunk_chars)
        result["report"] = chunks_path.name[:7]
        results.append(result)

    columns = list(THRESHOLDS)
    print(f"{'report':8}" + "".join(f"{c[:14]:>16}" for c in columns))
    for r in results:
        cells = [f"{r[c]}{'' if r['grades'][c] == 'ok' else ' ' + r['grades'][c]}" for c in columns]
        print(f"{r['report']:8}" + "".join(f"{c:>16}" for c in cells))
        for key in ("missing_chapter_titles", "garbage_title_examples", "low_recall_pages", "duplicate_parent_examples"):
            if r[key]:
                print(f"         {key}: {r[key]}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2, ensure_ascii=False))

    failed = [r["report"] for r in results if r["status"] == "FAIL"]
    print(f"\n{len(results)} report(s) checked, {len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
