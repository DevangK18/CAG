"""
Preflight checks: compare a report's *_chunks.json with its source PDF.

Every check compares the output with the PDF itself or with its own structure, so it
catches defects that pipeline logs and success counters do not report.

Checks (per report):
- word_recall         share of PDF words present in chunks cited on that page (±1)
- number_recall       same for numbers (amounts, years): catches dropped/reversed tables
- citation            chunks whose numbers are not on their cited page (wrong page refs)
- chunk_size          child chunks too long to embed
- reversed_text       word-reversed chunks ("tnemtrapeD fo eunever")
- shifted_font        text in fonts mapped 29 code points low ("&KDSWHU")
- split_cells         table cells cut mid-word ("Activity Typ | e")
- chapters            printed-contents chapters missing from parent (L1) titles
- garbage_titles      parent titles that are not headings
- dlq_leak            DLQ pages beyond the report's page count (state leak between reports)
- duplicate_parents   parent chunk IDs that occur more than once
- outside_parent      children cited outside their parent's page range
- largest_parent      share of all children under the single largest parent
"""

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import fitz  # PyMuPDF

from src.parsing_pipeline.extractors.text_repair import (
    _is_shifted_line,
    is_reversed,
    is_shifted_span,
    repair_font_shift,
    shifted_fonts,
    unshift,
)
from src.parsing_pipeline.modules.printed_toc_parser import (
    CHAPTER_RE,
    parse_printed_toc,
)
from src.parsing_pipeline.modules.toc_quality import is_garbage_title

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
    # Clean reports sit at 0 duplicates, <=1.1% outside and <=20% under one parent;
    # BR (P7-01) has 310 duplicates and 35.5% outside
    "duplicate_parents": (0, 0),
    "outside_parent_pct": (2.0, 10.0),
    "largest_parent_pct": (25.0, 50.0),
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
        pages.update(
            p for p in structured.get("source_pages") or [] if isinstance(p, int)
        )
    # A null cited page must not break sorting or min/max
    return sorted(p for p in pages if isinstance(p, int))


BAND = 0.09  # share of the page height treated as header/footer band


def _body_text(page) -> str:
    height = page.rect.height or 1.0
    textpage = page.get_textpage(flags=fitz.TEXTFLAGS_BLOCKS)
    layout = textpage.extractRAWDICT()
    fonts = shifted_fonts(layout)
    if fonts:
        # Shifted fonts decoded by font, as the extraction does: per line, short lines
        # and the digits below U+0020 stayed undecoded and counted against the output
        blocks = [
            (
                *b["bbox"],
                "\n".join(
                    "".join(
                        unshift(c["c"]) if is_shifted_span(span, fonts) else c["c"]
                        for span in line["spans"]
                        for c in span["chars"]
                    )
                    for line in b["lines"]
                ),
                0,
                0,
            )
            for b in layout["blocks"]
            if b.get("type") == 0
        ]
    else:
        blocks = textpage.extractBLOCKS()
    return "\n".join(
        b[4]
        for b in blocks
        if b[6] == 0 and not (b[3] < BAND * height or b[1] > (1 - BAND) * height)
    )


def default_max_chunk_chars() -> int:
    from src.parsing_pipeline.config import get_config

    return int(
        get_config().chunking.max_child_chunk_chars * 1.1
    )  # headroom for split pieces


def _structure_metrics(children: List[Dict], parents: List[Dict]) -> Dict[str, Any]:
    """Parent/child structure checks that need no PDF (X-01)."""
    ids = Counter(p.get("chunk_id") for p in parents)
    duplicates = sum(n - 1 for n in ids.values() if n > 1)

    by_id = {p.get("chunk_id"): p for p in parents}
    checked = outside = 0
    for chunk in children:
        parent = by_id.get(chunk.get("parent_chunk_id"))
        page = chunk.get("source_page_physical")
        page_range = (parent or {}).get("page_range_physical")
        if not isinstance(page, int) or not (
            isinstance(page_range, (list, tuple)) and len(page_range) == 2
        ):
            continue
        checked += 1
        outside += not (page_range[0] <= page <= page_range[1])

    per_parent = Counter(c.get("parent_chunk_id") for c in children)
    largest_id, largest_n = per_parent.most_common(1)[0] if per_parent else (None, 0)
    return {
        "duplicate_parents": duplicates,
        "duplicate_parent_examples": [i for i, n in ids.most_common(5) if n > 1],
        "outside_parent": outside,
        "outside_parent_pct": round(100 * outside / checked, 1) if checked else 0.0,
        "largest_parent_pct": round(100 * largest_n / len(children), 1)
        if children
        else 0.0,
        "largest_parent_title": (by_id.get(largest_id) or {}).get("toc_entry"),
    }


def check_report(
    chunks_json: Dict[str, Any],
    pdf_path: Union[str, Path],
    max_chunk_chars: Optional[int] = None,
) -> Dict[str, Any]:
    """Run every check on one report; returns metrics, grades, red flags and status."""
    if max_chunk_chars is None:
        max_chunk_chars = default_max_chunk_chars()
    data = chunks_json
    children, parents = data.get("child_chunks") or [], data.get("parent_chunks") or []
    with fitz.open(str(pdf_path)) as doc:
        # Decode font-shifted lines so they compare with the repaired output. Running
        # headers, footers and page numbers sit in the top/bottom bands and are dropped
        # on purpose, so they are not expected in the chunks
        page_text = [repair_font_shift(_body_text(page)) for page in doc]
        printed, _ = parse_printed_toc(doc)
        page_count = doc.page_count
    pdf_vocab = set(WORD_RE.findall(" ".join(page_text).lower()))

    by_page = defaultdict(str)
    for chunk in children:
        for page in chunk_pages(chunk):
            by_page[page] += " " + (chunk.get("content") or "")

    # Recall per page, allowing content cited one page off (cross-page paragraphs)
    word_expected, word_found, num_expected, num_found = (
        Counter(),
        Counter(),
        Counter(),
        Counter(),
    )
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
        pages = chunk_pages(chunk)
        if sum(found.values()) < 5 or not pages:
            continue
        cited = " ".join(
            page_text[p]
            for p in range(min(pages) - 1, max(pages) + 2)
            if 0 <= p < len(page_text)
        )
        checked += 1
        if recall(found, numbers(cited)) < 0.5:
            miscited += 1

    # Table cells split mid-word: "Typ | e" where "type" is a word in this PDF
    tables = [c for c in children if c.get("content_type") == "table_markdown"]
    split_tables = 0
    for table in tables:
        splits = sum(
            1
            for a, b in SPLIT_CELL_RE.findall(table.get("content") or "")
            if (a + b).lower() in pdf_vocab
            and a.lower() not in pdf_vocab
            and b.lower() not in pdf_vocab
        )
        split_tables += splits >= 2

    text_chunks = [c for c in children if c.get("content_type") != "image_caption"]
    reversed_count = sum(1 for c in text_chunks if is_reversed(c.get("content") or ""))
    shifted = sum(
        1
        for text in [c.get("content") or "" for c in children]
        + [p.get("toc_entry") or "" for p in parents]
        for line in text.split("\n")
        if _is_shifted_line(line)
    )

    # Chapters in the printed contents vs parent L1 titles
    def norm(t):
        return re.sub(r"[^a-z0-9]", "", t.lower())

    l1_titles = [
        norm(p.get("toc_entry") or "") for p in parents if p.get("toc_level") == 1
    ]
    printed_chapters = [
        t for level, t, _ in printed if level == 1 and CHAPTER_RE.match(t)
    ]
    missing = [
        t
        for t in printed_chapters
        if not any(norm(t)[:25] in l1 or l1[:25] in norm(t) for l1 in l1_titles if l1)
    ]
    garbage = [
        p.get("toc_entry")
        for p in parents
        if is_garbage_title(p.get("toc_entry") or "")
    ]

    dlq = (data.get("processing_stats") or {}).get("dlq_entries") or []
    dlq_leak = sum(
        1 for e in dlq if isinstance(e, dict) and (e.get("page") or 0) >= page_count
    )

    lengths = [len(c.get("content") or "") for c in children]
    result = {
        "report": (data.get("report_metadata") or {}).get("report_id", ""),
        "pages": page_count,
        "children": len(children),
        "parents": len(parents),
        "word_recall": round(recall(word_expected, word_found), 3),
        "number_recall": round(recall(num_expected, num_found), 3),
        "low_recall_pages": low_pages[:20],
        "citation_pct": round(100 * miscited / checked, 1) if checked else 0.0,
        "max_chunk_chars": max(lengths) if lengths else 0,
        "oversized_chunks": sum(1 for n in lengths if n > max_chunk_chars),
        "reversed_pct": round(100 * reversed_count / len(text_chunks), 2)
        if text_chunks
        else 0.0,
        "shifted_lines": shifted,
        "split_cell_tables_pct": round(100 * split_tables / len(tables), 1)
        if tables
        else 0.0,
        "missing_chapters": len(missing),
        "missing_chapter_titles": missing,
        "garbage_titles": len(garbage),
        "garbage_title_examples": garbage[:5],
        "dlq_leak": dlq_leak,
        **_structure_metrics(children, parents),
    }
    result["grades"] = grade(result)
    result["red_flags"] = red_flags(result, result["grades"])
    result["status"] = status(result["grades"])
    return result


def grade(result: Dict) -> Dict[str, str]:
    grades = {}
    for key, (warn, fail) in THRESHOLDS.items():
        value = result[key]
        if key.endswith("recall"):
            grades[key] = "FAIL" if value < fail else "WARN" if value < warn else "ok"
        else:
            grades[key] = "FAIL" if value > fail else "WARN" if value > warn else "ok"
    return grades


def red_flags(result: Dict, grades: Dict[str, str]) -> List[Dict[str, Any]]:
    """One entry per check graded FAIL or WARN, with the value and its thresholds."""
    return [
        {
            "check": key,
            "grade": g,
            "value": result[key],
            "warn": THRESHOLDS[key][0],
            "fail": THRESHOLDS[key][1],
        }
        for key, g in grades.items()
        if g != "ok"
    ]


def status(grades: Dict[str, str]) -> str:
    values = set(grades.values())
    return "FAIL" if "FAIL" in values else "WARN" if "WARN" in values else "ok"


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compact per-report line for the run summary."""
    if "error" in result:
        return {"status": "error", "error": result["error"]}
    flags = result.get("red_flags") or []
    return {
        "status": result.get("status"),
        "fail": [f["check"] for f in flags if f["grade"] == "FAIL"],
        "warn": [f["check"] for f in flags if f["grade"] == "WARN"],
        "word_recall": result.get("word_recall"),
        "number_recall": result.get("number_recall"),
    }
