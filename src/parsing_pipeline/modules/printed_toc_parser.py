"""
Printed Table of Contents parser.

CAG reports print a contents page listing chapters, numbered sections and annexures with
printed page numbers. The text layer splits each entry over several lines (number /
title / page), so line-by-line regexes found only 3-6 entries. This parser groups words
into visual rows by position, parses "[number] title page[-page]" per row, joins wrapped
titles, and maps printed page numbers to physical pages using the page numbers printed
on each page.
"""

import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from src.parsing_pipeline.extractors.text_repair import repair_font_shift

logger = logging.getLogger(__name__)

CONTENTS_HEADING_RE = re.compile(r"^\s*(table\s+of\s+)?contents?\s*$|^\s*index\s*$", re.IGNORECASE)
HEADER_WORDS = {
    "particulars", "page", "pages", "no", "no.", "nos", "paragraph", "para", "chapter",
    "chapter/", "/", "subject", "title", "contents", "content", "table", "of", "index",
    "sl", "sl.", "s.", "sr.", "description", "sub-para", "sub-", "sub", "reference", "number", "topic",
}
RUNNING_HEADER_RE = re.compile(r"^(audit\s+)?report\s+no\.?\s*\d+\s+of\s+\d{4}\b.{0,40}$", re.IGNORECASE)
ENTRY_START_RE = re.compile(
    r"^(chapter|part|annexure|appendix)\b|^\d+(\.\d+)*\.?\s+[A-Z(]|^(preface|executive summary|glossary|abbreviations)\b",
    re.IGNORECASE,
)
ROMAN = r"[ivxlcIVXLC]{1,7}"
PAGE_TAIL_RE = re.compile(
    rf"^(?P<body>.*?)[\s.·…_-]*\s(?P<start>\d{{1,3}}|{ROMAN})(?:\s*[-–—]\s*(?P<end>\d{{1,3}}|{ROMAN}))?\s*$"
)
NUMBERED_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>.+)$")
CHAPTER_RE = re.compile(r"^(chapter|part)\s*[-:]?\s*([ivxlc]+|\d+)\b", re.IGNORECASE)
FRONT_BACK_RE = re.compile(
    r"^(preface|foreword|executive\s+summary|overview|abbreviations?|glossary|annexures?|"
    r"appendices|appendix|list\s+of\s+\w+|conclusions?|recommendations|acknowledge?ment|"
    r"audit\s+(summary|findings)|key\s+audit\s+findings)\b",
    re.IGNORECASE,
)
ANNEX_ITEM_RE = re.compile(r"^(annexure|appendix)[\s-]*[\w.()]+", re.IGNORECASE)

ENUMERATOR_RE = re.compile(
    r"^\s*(chapter|part)?\s*[-:]?\s*(\(?[ivxlc]+[.)]|\(?[a-z][.)]|\d+(\.\d+)*\.?|[ivxlc]+\b)?\s*[-:–]?\s*",
    re.IGNORECASE,
)

MAX_CONTENTS_SCAN_PAGES = 20
ROW_Y_TOLERANCE = 3.0


def roman_to_int(text: str) -> Optional[int]:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    text = text.lower()
    if not text or any(c not in values for c in text):
        return None
    total = 0
    for i, c in enumerate(text):
        v = values[c]
        total += -v if i + 1 < len(text) and values[text[i + 1]] > v else v
    return total


def _page_rows(page: fitz.Page) -> List[str]:
    """Group words into visual rows (same baseline), left to right."""
    words = page.get_text("words")
    rows: List[List[tuple]] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        y = (w[1] + w[3]) / 2
        if rows and abs(((rows[-1][0][1] + rows[-1][0][3]) / 2) - y) <= ROW_Y_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [
        repair_font_shift(" ".join(w[4] for w in sorted(row, key=lambda w: w[0]))).strip()
        for row in rows
    ]


def _find_contents_start(doc: fitz.Document) -> Optional[int]:
    for i in range(min(MAX_CONTENTS_SCAN_PAGES, doc.page_count)):
        rows = _page_rows(doc[i])
        if any(CONTENTS_HEADING_RE.match(r) for r in rows[:8]):
            return i
    return None


def _is_header_row(row: str) -> bool:
    words = re.findall(r"[A-Za-z./-]+", row.lower())
    return bool(words) and all(w in HEADER_WORDS for w in words)


def _parse_rows(rows: List[str]) -> List[Tuple[str, Optional[str]]]:
    """
    Return (title, printed_page) per entry, joining wrapped title lines. Entries whose
    row has no page (a chapter heading followed by its sections) get page None.
    """
    entries: List[Tuple[str, Optional[str]]] = []
    pending = ""
    for row in rows:
        if not row or CONTENTS_HEADING_RE.match(row) or _is_header_row(row) or RUNNING_HEADER_RE.match(row):
            continue
        match = PAGE_TAIL_RE.match(row)
        body = match.group("body").strip() if match else row
        if pending and ENTRY_START_RE.match(body):
            if ENTRY_START_RE.match(pending):
                # "Chapter I: General" (no page) followed by "1.1 Introduction 1"
                entries.append((pending.strip(" .·…_-"), None))
            elif entries:
                # Wrapped second line of the previous title ("Raw Materials, Fuel & Services")
                title, page = entries[-1]
                entries[-1] = (f"{title} {pending}".strip(" .·…_-"), page)
            pending = ""
        if match and body:
            title = f"{pending} {body}".strip(" .·…_-")
            entries.append((title, match.group("start")))
            pending = ""
        elif not pending and entries and row[:1].islower():
            # Wrapped tail of the previous entry's title, printed after its page number
            title, page = entries[-1]
            entries[-1] = (f"{title} {row}".strip(" .·…_-"), page)
        elif re.fullmatch(r"\d{1,3}|" + ROMAN, row):
            # Page-number-only row (page printed below the title)
            if pending:
                entries.append((pending.strip(" .·…_-"), row))
                pending = ""
        else:
            pending = f"{pending} {row}".strip()
            if len(pending) > 250:  # prose, not a wrapped title
                pending = ""
    return entries


def _level(title: str, in_annexures: bool, in_chapter: bool) -> int:
    if CHAPTER_RE.match(title):
        return 1
    if ANNEX_ITEM_RE.match(title) and not re.match(r"^(annexures|appendices)\s*$", title, re.I):
        return 2 if in_annexures else 1
    if FRONT_BACK_RE.match(title):
        return 1
    numbered = NUMBERED_RE.match(title)
    if numbered:
        depth = numbered.group("num").count(".") + 1
        return min(depth, 4) if depth > 1 else (1 if not in_chapter else 2)
    return 2 if in_chapter else 1


def build_printed_page_map(doc: fitz.Document) -> Tuple[Dict[int, int], Dict[int, int]]:
    """
    Printed page number of each physical page ({physical: printed}), for arabic and roman
    numbering, read from the page number printed in the first/last lines. The offset is
    not constant: blank and unnumbered full-page tables shift it partway through.
    """
    arabic: Dict[int, int] = {}
    roman: Dict[int, int] = {}
    for i in range(doc.page_count):
        lines = [l.strip() for l in doc[i].get_text("text").split("\n") if l.strip()]
        for line in lines[:4] + lines[-4:]:
            if re.fullmatch(r"\d{1,3}", line):
                arabic[i] = int(line)
                break
            if re.fullmatch(r"[ivxlc]{1,6}", line):
                value = roman_to_int(line)
                if value:
                    roman[i] = value
                    break
    return arabic, roman


def _to_physical(printed: int, labels: Dict[int, int], min_page: int) -> Tuple[Optional[int], bool]:
    """
    Physical page printed with this number, interpolated from the nearest labelled page
    when no page carries it. Returns (page, exact_label_match).
    """
    exact = sorted(i for i, label in labels.items() if label == printed and i >= min_page)
    if exact:
        return exact[0], True
    below = [(i, label) for i, label in labels.items() if label < printed and i >= min_page]
    if below:
        i, label = max(below, key=lambda x: x[1])
        return i + (printed - label), False
    above = [(i, label) for i, label in labels.items() if label > printed and i >= min_page]
    if above:
        i, label = min(above, key=lambda x: x[1])
        return i - (label - printed), False
    return None, False


def parse_printed_toc(doc: fitz.Document, report_id: str = "unknown") -> Tuple[List[List], float]:
    """
    Parse the printed contents page(s).

    Returns:
        ([[level, title, physical_page], ...], confidence 0-1). Confidence is the share of
        entries whose title is actually found on (or next to) the mapped page.
    """
    start = _find_contents_start(doc)
    if start is None:
        return [], 0.0

    raw_entries: List[Tuple[str, str]] = []
    contents_end = start
    for i in range(start, min(start + 8, doc.page_count)):
        page_entries = _parse_rows(_page_rows(doc[i]))
        if i > start and len(page_entries) < 3:
            break
        raw_entries.extend(page_entries)
        contents_end = i

    if len(raw_entries) < 3:
        return [], 0.0

    arabic, roman = build_printed_page_map(doc)
    toc: List[List] = []
    exact_pages = set()
    in_annexures = in_chapter = False
    for idx, (title, printed) in enumerate(raw_entries):
        title = re.sub(r"\s+", " ", title).strip()
        # Stray page token from a second page column: "Glossary i", "Annexures i"
        title = re.sub(r"\s+[ivxlc]{1,4}$", "", title)
        if len(title) < 3:
            continue
        if printed is None:
            # Unnumbered heading (Preface, or a chapter line above its sections): find it
            # before the next numbered entry
            next_page = _next_page(raw_entries, idx, arabic, roman, contents_end)
            if FRONT_BACK_RE.match(title):
                # Only front/back matter is searched for: chapter titles also appear in
                # the Executive Summary, which would pull them too early
                first = max([contents_end + 1] + [e[2] for e in toc])
                physical = _find_title_page(doc, title, first, next_page)
            else:
                physical = next_page
            if physical is not None:
                level = _level(title, in_annexures, in_chapter)
                if level == 1:
                    in_chapter = bool(CHAPTER_RE.match(title))
                    in_annexures = bool(re.match(r"^(annexures?|appendices)\s*$", title, re.I))
                toc.append([level, title, physical])
            continue
        # Page numbers listed on the contents pages must not label those pages
        if printed.isdigit():
            physical, exact = _to_physical(int(printed), arabic, contents_end + 1)
        else:
            value = roman_to_int(printed)
            physical, exact = _to_physical(value, roman, contents_end + 1) if value else (None, False)
        if physical is None or not 0 <= physical < doc.page_count:
            continue
        level = _level(title, in_annexures, in_chapter)
        if level == 1:
            in_chapter = bool(CHAPTER_RE.match(title))
            in_annexures = bool(re.match(r"^(annexures?|appendices)\s*$", title, re.I))
        toc.append([level, title, physical])
        if exact:
            exact_pages.add(len(toc) - 1)

    if len(toc) < 3:
        return [], 0.0

    confidence = _verify_on_pages(doc, toc, exact_pages)
    logger.info(
        f"[{report_id}] Printed TOC: {len(toc)} entries from page {start}, "
        f"verified {confidence:.0%}"
    )
    return toc, confidence


def _printed_to_physical(printed: str, arabic, roman, min_page: int) -> Optional[int]:
    if printed.isdigit():
        return _to_physical(int(printed), arabic, min_page)[0]
    value = roman_to_int(printed)
    return _to_physical(value, roman, min_page)[0] if value else None


def _next_page(entries, idx, arabic, roman, contents_end) -> Optional[int]:
    """Physical page of the next entry that has a printed page number."""
    for _, printed in entries[idx + 1:]:
        if printed is not None:
            return _printed_to_physical(printed, arabic, roman, contents_end + 1)
    return None


def _find_title_page(doc: fitz.Document, title: str, first: int, last: Optional[int]) -> Optional[int]:
    """First page in [first, last] whose opening text contains the title; else `last`."""
    key = _normalize(ENUMERATOR_RE.sub("", title))[:30]
    end = min(last if last is not None else first + 30, doc.page_count - 1)
    for i in range(first, end + 1):
        if key and key in _normalize(repair_font_shift(doc[i].get_text("text")))[:600]:
            return i
    return last


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _verify_on_pages(doc: fitz.Document, toc: List[List], exact_pages: set) -> float:
    """
    Share of entries confirmed on the document: the mapped page prints that page number,
    or the title text appears on the mapped page (±1). Chapter banners are often images,
    so title text alone under-counts.
    """
    cache: Dict[int, str] = {}

    def page_text(i: int) -> str:
        if i not in cache:
            cache[i] = _normalize(repair_font_shift(doc[i].get_text("text"))) if 0 <= i < doc.page_count else ""
        return cache[i]

    hits = 0
    for idx, (_, title, page) in enumerate(toc):
        if idx in exact_pages:
            hits += 1
            continue
        # Contents may number sections "i." / "(a)" where the body uses "1.1"
        key = _normalize(ENUMERATOR_RE.sub("", title))[:30]
        if key and any(key in page_text(p) for p in (page - 1, page, page + 1)):
            hits += 1
    return hits / len(toc)
