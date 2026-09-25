#!/usr/bin/env python3
"""
Pre-flight check: compare parsing pipeline output against the source PDFs
==========================================================================

Run on a few reports locally before launching a full VM run. Every check compares
the *_chunks.json output with the PDF itself, so it catches defects that pipeline
logs and success counters do not report.

Checks (per report):
- word_recall      share of PDF words present in chunks cited on that page (±1)
- number_recall    same for numbers (amounts, years): catches dropped/reversed tables
- citation         chunks whose numbers are not on their cited page (wrong page refs)
- chunk_size       child chunks too long to embed
- reversed_text    word-reversed chunks ("tnemtrapeD fo eunever")
- shifted_font     text in fonts mapped 29 code points low ("&KDSWHU")
- split_cells      table cells cut mid-word ("Activity Typ | e")
- chapters         printed-contents chapters missing from parent (L1) titles
- garbage_titles   parent titles that are not headings
- dlq_leak         DLQ pages beyond the report's page count (state leak between reports)

Usage:
    python scripts/evaluation/preflight_check.py \\
        --processed-dir data/processed/union --pdf-dir data/raw/union \\
        --reports 2025_04 2023_19 --json-out preflight.json

Exit code 1 if any check fails.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.parsing_pipeline.config import get_config  # noqa: E402
from src.parsing_pipeline.extractors.text_repair import _is_shifted_line, is_reversed, repair_font_shift  # noqa: E402
from src.parsing_pipeline.modules.printed_toc_parser import CHAPTER_RE, parse_printed_toc  # noqa: E402
from src.parsing_pipeline.modules.toc_quality import is_garbage_title  # noqa: E402

WORD_RE = re.compile(r"[a-z]{3,}")
NUMBER_RE = re.compile(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{2,3})+|\d{4,}")
SPLIT_CELL_RE = re.compile(r"([A-Za-z]{2,}) \| ([a-z]{1,6})\b")

# (warn, fail) thresholds; recall checks fail below, count checks fail above
THRESHOLDS = {
    "word_recall": (0.95, 0.90),
    "number_recall": (0.93, 0.85),
    "citation_pct": (5.0, 15.0),
    "oversized_chunks": (0, 0),
    "reversed_pct": (0.2, 1.0),
    "shifted_lines": (0, 5),
    "split_cell_tables_pct": (5.0, 15.0),
    "missing_chapters": (0, 1),
    "garbage_titles": (2, 5),
    "dlq_leak": (0, 0),
}


def words(text: str) -> Counter:
    return Counter(WORD_RE.findall(text.lower()))


def numbers(text: str) -> Counter:
    return Counter(n.replace(",", "") for n in NUMBER_RE.findall(text))


def recall(expected: Counter, found: Counter) -> float:
    total = sum(expected.values())
    return sum(min(n, found[t]) for t, n in expected.items()) / total if total else 1.0


def chunk_pages(chunk: Dict) -> List[int]:
    """Pages a chunk covers: its cited page plus any table fragment pages."""
    pages = {chunk.get("source_page_physical", 0)}
    structured = chunk.get("structured_data") or {}
    if isinstance(structured, dict):
        pages.update(p for p in structured.get("source_pages") or [] if isinstance(p, int))
    return sorted(pages)


def check_report(chunks_path: Path, pdf_path: Path, max_chunk_chars: int) -> Dict:
    data = json.loads(chunks_path.read_text())
    children, parents = data["child_chunks"], data["parent_chunks"]
    doc = fitz.open(pdf_path)
    # Decode font-shifted lines so they compare with the repaired output
    page_text = [repair_font_shift(page.get_text("text")) for page in doc]
    pdf_vocab = set(WORD_RE.findall(" ".join(page_text).lower()))

    by_page = defaultdict(str)
    for chunk in children:
        for page in chunk_pages(chunk):
            by_page[page] += " " + (chunk.get("content") or "")

    # Recall per page, allowing content cited one page off (cross-page paragraphs)
    word_expected, word_found, num_expected, num_found = Counter(), Counter(), Counter(), Counter()
    low_pages = []
    for i, text in enumerate(page_text):
        expected_w, expected_n = words(text), numbers(text)
        if sum(expected_w.values()) < 30:
            continue
        nearby = " ".join(by_page.get(p, "") for p in (i - 1, i, i + 1))
        got_w, got_n = words(nearby), numbers(nearby)
        page_recall = recall(expected_w, got_w)
        if page_recall < 0.5:
            low_pages.append(i)
        for token, n in expected_w.items():
            word_expected[token] += n
            word_found[token] += min(n, got_w[token])
        for token, n in expected_n.items():
            num_expected[token] += n
            num_found[token] += min(n, got_n[token])

    # Citation: chunk numbers should appear on the pages it cites (±1)
    checked = miscited = 0
    for chunk in children:
        found = numbers(chunk.get("content") or "")
        if sum(found.values()) < 5:
            continue
        pages = chunk_pages(chunk)
        cited = " ".join(page_text[p] for p in range(min(pages) - 1, max(pages) + 2) if 0 <= p < len(page_text))
        checked += 1
        if recall(found, numbers(cited)) < 0.5:
            miscited += 1

    # Table cells split mid-word: "Typ | e" where "type" is a word in this PDF
    tables = [c for c in children if c.get("content_type") == "table_markdown"]
    split_tables = 0
    for table in tables:
        splits = sum(
            1 for a, b in SPLIT_CELL_RE.findall(table.get("content") or "")
            if (a + b).lower() in pdf_vocab and a.lower() not in pdf_vocab and b.lower() not in pdf_vocab
        )
        split_tables += splits >= 2

    text_chunks = [c for c in children if c.get("content_type") != "image_caption"]
    reversed_count = sum(1 for c in text_chunks if is_reversed(c.get("content") or ""))
    shifted = sum(
        1
        for text in [c.get("content") or "" for c in children] + [p.get("toc_entry") or "" for p in parents]
        for line in text.split("\n")
        if _is_shifted_line(line)
    )

    # Chapters in the printed contents vs parent L1 titles
    printed, _ = parse_printed_toc(doc)
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    l1_titles = [norm(p.get("toc_entry") or "") for p in parents if p.get("toc_level") == 1]
    printed_chapters = [t for level, t, _ in printed if level == 1 and CHAPTER_RE.match(t)]
    missing = [t for t in printed_chapters if not any(norm(t)[:25] in l1 or l1[:25] in norm(t) for l1 in l1_titles if l1)]
    garbage = [p.get("toc_entry") for p in parents if is_garbage_title(p.get("toc_entry") or "")]

    dlq = (data.get("processing_stats") or {}).get("dlq_entries") or []
    dlq_leak = sum(1 for e in dlq if isinstance(e, dict) and e.get("page", 0) >= doc.page_count)

    lengths = [len(c.get("content") or "") for c in children]
    return {
        "report": chunks_path.name[:7],
        "pages": doc.page_count,
        "children": len(children),
        "parents": len(parents),
        "word_recall": round(recall(word_expected, word_found), 3),
        "number_recall": round(recall(num_expected, num_found), 3),
        "low_recall_pages": low_pages[:20],
        "citation_pct": round(100 * miscited / checked, 1) if checked else 0.0,
        "max_chunk_chars": max(lengths) if lengths else 0,
        "oversized_chunks": sum(1 for n in lengths if n > max_chunk_chars),
        "reversed_pct": round(100 * reversed_count / len(text_chunks), 2) if text_chunks else 0.0,
        "shifted_lines": shifted,
        "split_cell_tables_pct": round(100 * split_tables / len(tables), 1) if tables else 0.0,
        "missing_chapters": len(missing),
        "missing_chapter_titles": missing,
        "garbage_titles": len(garbage),
        "garbage_title_examples": garbage[:5],
        "dlq_leak": dlq_leak,
    }


def grade(result: Dict) -> Dict[str, str]:
    grades = {}
    for key, (warn, fail) in THRESHOLDS.items():
        value = result[key]
        if key.endswith("recall"):
            grades[key] = "FAIL" if value < fail else "WARN" if value < warn else "ok"
        else:
            grades[key] = "FAIL" if value > fail else "WARN" if value > warn else "ok"
    return grades


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--processed-dir", default="data/processed/union")
    parser.add_argument("--pdf-dir", default="data/raw/union")
    parser.add_argument("--reports", nargs="*", help="Report id prefixes (e.g. 2025_04); default all")
    parser.add_argument("--json-out", help="Write full results as JSON")
    args = parser.parse_args()

    max_chunk_chars = int(get_config().chunking.max_child_chunk_chars * 1.1)  # headroom for split pieces
    results = []
    for chunks_path in sorted(Path(args.processed_dir).glob("*_chunks.json")):
        report_id = chunks_path.name[: -len("_chunks.json")]
        if args.reports and not any(report_id.startswith(r) for r in args.reports):
            continue
        pdf_path = Path(args.pdf_dir) / f"{report_id}.pdf"
        if not pdf_path.exists():
            print(f"skip {report_id}: no PDF at {pdf_path}")
            continue
        result = check_report(chunks_path, pdf_path, max_chunk_chars)
        result["grades"] = grade(result)
        results.append(result)

    columns = list(THRESHOLDS)
    print(f"{'report':8}" + "".join(f"{c[:14]:>16}" for c in columns))
    for r in results:
        cells = [f"{r[c]}{'' if r['grades'][c] == 'ok' else ' ' + r['grades'][c]}" for c in columns]
        print(f"{r['report']:8}" + "".join(f"{c:>16}" for c in cells))
        for key in ("missing_chapter_titles", "garbage_title_examples", "low_recall_pages"):
            if r[key]:
                print(f"         {key}: {r[key]}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2, ensure_ascii=False))

    failed = [r["report"] for r in results if "FAIL" in r["grades"].values()]
    print(f"\n{len(results)} report(s) checked, {len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
