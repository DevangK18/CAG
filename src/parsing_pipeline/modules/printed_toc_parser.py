"""
Printed Table of Contents parser.

CAG reports print a contents page listing chapters, numbered sections and annexures with
printed page numbers. The text layer splits each entry over several lines (number /
title / page), so line-by-line regexes found only 3-6 entries. This parser groups words
into visual rows by position, parses "[number] title [para] page[-page]" per row
(union reports print Number | Title | Page, state and local ones Title | Para | Page),
gives wrapped and vertically centred title lines to their row by the vertical gaps,
and maps printed page numbers to physical pages using the page number printed in each
page's header or footer (`build_printed_page_map`, also the source of logical pages).
"""

import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from src.parsing_pipeline.extractors.text_repair import repair_font_shift, unshift

logger = logging.getLogger(__name__)

CONTENTS_HEADING_RE = re.compile(
    r"^\s*(table\s+of\s+)?contents?\s*$|^\s*index\s*$", re.IGNORECASE
)
# Column headers, including the three-column "Reference to / CHAPTER DESCRIPTION /
# Paragraphs Page" and "Appendix No. Description Page No."
HEADER_WORDS = {
    "particulars",
    "page",
    "pages",
    "no",
    "no.",
    "nos",
    "paragraph",
    "paragraphs",
    "para",
    "chapter",
    "chapter/",
    "/",
    "subject",
    "title",
    "contents",
    "content",
    "table",
    "of",
    "index",
    "sl",
    "sl.",
    "s.",
    "sr.",
    "description",
    "sub-para",
    "sub-",
    "sub",
    "reference",
    "to",
    "number",
    "topic",
    "appendix",
    "annexure",
    "details",
}
# "Report No. 8 of 2025", "Report No.6 of the year 2022", "Audit Report (Local Government)
# for the year ended March 2022", "State Finances Audit Report for the year ended 31 March 2024"
RUNNING_HEADER_RE = re.compile(
    r"^(audit\s+)?report\s+no\.?\s*\d*\s+of\s+(the\s+year\s+)?\d{4}\b.{0,40}$"
    r"|^.{0,40}\breport\b.{0,40}\bfor\s+the\s+(year|period)\s+ended\b.{0,20}$",
    re.IGNORECASE,
)
ROMAN = r"[ivxlcIVXLC]{1,7}"
PAGE_TAIL_RE = re.compile(
    rf"^(?P<body>.*?)[\s.·…_-]*\s(?P<start>\d{{1,3}}|{ROMAN})(?:\s*[-–—]\s*(?P<end>\d{{1,3}}|{ROMAN}))?\s*$"
)
NUMBERED_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>.+)$")
CHAPTER_RE = re.compile(r"^(chapter|part)\s*[-:]?\s*([ivxlc]+|\d+)\b", re.IGNORECASE)
# "I AN OVERVIEW OF ...", "II COMPLIANCE AUDIT" (BR); "PART-A", "Part B"
ROMAN_CHAPTER_RE = re.compile(r"^[IVX]{1,4}\s+[A-Z][A-Z]")
PART_RE = re.compile(r"^part\s*[-:]?\s*[a-z]\b", re.IGNORECASE)
# A chapter label alone on its row: its number is not a page ("CHAPTER I", "Chapter 2")
CHAPTER_ONLY_RE = re.compile(
    r"^(chapter|part)\s*[-:.]?\s*([ivxlc]+|\d+)$", re.IGNORECASE
)
APPENDIX_BLOCK_RE = re.compile(
    r"^(list\s+of\s+)?(annexures?|appendices)\s*$", re.IGNORECASE
)
FRONT_BACK_RE = re.compile(
    r"^(preface|foreword|executive\s+summary|overview|abbreviations?|glossary|annexures?|"
    r"appendices|appendix|list\s+of\s+\w+|conclusions?|recommendations|acknowledge?ment|"
    r"audit\s+(summary|findings)|key\s+audit\s+findings)\b",
    re.IGNORECASE,
)
ANNEX_ITEM_RE = re.compile(r"^(annexure|appendix)[\s-]*[\w.()]+", re.IGNORECASE)
# A label line printed above or beside its title cell: "Appendix 1.1"
ANNEX_LABEL_RE = re.compile(
    r"^(annexure|appendix)[\s-]*\d+(\.\d+)*(\s*\([A-Za-z]\))?$", re.IGNORECASE
)
# The number at the start of an entry: "Chapter-1", "Chapter III", "Appendix 2.1", "5.2 (A)", "1.2"
LEAD_RE = re.compile(
    r"^(?P<lead>(?:chapter|part|appendix|annexure)\s*[-:.]?\s*(?:[ivxlc]+|\d+(?:\.\d+)*|[a-z])\b(?:\s*\([A-Za-z]\))?"
    r"|\d+(?:\.\d+)*(?:\s*\([A-Za-z]\))?)(?P<punct>[.:]?)(?:\s+|$)(?P<rest>.*)$",
    re.IGNORECASE,
)
# The para number column of a Title | Para | Page row: "Audit objectives 1.2 3"
PARA_TAIL_RE = re.compile(
    r"^(?P<body>.*?)\s*(?<![\w.])(?P<para>\d+(?:\.\d+)+(?:\s*\((?:[ivx]+|[A-Za-z])\))?)$"
)
# Appendix number column of an ATIR appendix list: "Detail of 15-line departments 2 62"
APPENDIX_NO_TAIL_RE = re.compile(r"^(?P<body>.*?)\s+(?P<num>\d{1,2})$")

ENUMERATOR_RE = re.compile(
    r"^\s*(chapter|part)?\s*[-:]?\s*(\(?[ivxlc]+[.)]|\(?[a-z][.)]|\d+(\.\d+)*\.?|[ivxlc]+\b)?\s*[-:–]?\s*",
    re.IGNORECASE,
)

MAX_CONTENTS_SCAN_PAGES = 20
ROW_Y_TOLERANCE = 3.0
# Rows this close in the vertical-gap split count as the same distance
GAP_TIE = 1.5


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


def _page_rows_y(page: fitz.Page) -> List[Tuple[float, str]]:
    """Group words into visual rows (same baseline), left to right; (mid y, text) per row."""
    words = page.get_text("words")
    rows: List[List[tuple]] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        y = (w[1] + w[3]) / 2
        if rows and abs(((rows[-1][0][1] + rows[-1][0][3]) / 2) - y) <= ROW_Y_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [
        (
            (row[0][1] + row[0][3]) / 2,
            repair_font_shift(
                " ".join(w[4] for w in sorted(row, key=lambda w: w[0]))
            ).strip(),
        )
        for row in rows
    ]


def _page_rows(page: fitz.Page) -> List[str]:
    """Group words into visual rows (same baseline), left to right."""
    return [text for _, text in _page_rows_y(page)]


def _find_contents_start(doc: fitz.Document) -> Optional[int]:
    for i in range(min(MAX_CONTENTS_SCAN_PAGES, doc.page_count)):
        rows = _page_rows(doc[i])
        if any(CONTENTS_HEADING_RE.match(r) for r in rows[:8]):
            return i
    return None


def _is_header_row(row: str) -> bool:
    if re.search(r"\d", row):
        return False
    words = re.findall(r"[A-Za-z./-]+", row.lower())
    return bool(words) and all(w in HEADER_WORDS for w in words)


def is_chapter_title(title: str) -> bool:
    """Chapter or part heading: "Chapter-1 ...", "CHAPTER III", "I AN OVERVIEW ...", "PART-A"."""
    return bool(
        CHAPTER_RE.match(title) or ROMAN_CHAPTER_RE.match(title) or PART_RE.match(title)
    )


def _is_caps(text: str) -> bool:
    """A heading set in capitals; not a wrapped acronym line such as "CPSEs)" or "(HOCL)"."""
    letters = [c for c in text if c.isalpha()]
    return (
        len(text.split()) >= 3
        and len(letters) >= 12
        and text[:1].isalnum()
        and sum(c.isupper() for c in letters) >= 0.8 * len(letters)
    )


class _Entry:
    """One contents entry being assembled from its page row and the lines around it."""

    def __init__(
        self,
        y: float,
        lead: str,
        text: str,
        page: Optional[str],
        appendix: bool = False,
    ):
        self.y, self.lead, self.page, self.appendix = y, lead, page, appendix
        self.bottom_y = y  # y of its lowest line, for the gap to the next row
        self.prefix: List[str] = []
        self.text = text
        self.suffix: List[str] = []

    @property
    def needs_title(self) -> bool:
        return not self.text and not self.prefix

    def title(self) -> str:
        body = ""
        for part in (p for p in self.prefix + [self.text] + self.suffix if p):
            # A hyphen at a line break joins the word ("persons-in-" / "position")
            body += part if re.search(r"\w[-–]$", body) else f" {part}"
        return re.sub(r"\s+", " ", f"{self.lead} {body}").strip(" .·…_-–")


def _parse_page_row(match: "re.Match", in_appendix: bool) -> Tuple[str, str]:
    """(lead number, title text) of a row with a page number, from its body."""
    body = match.group("body").strip(" .·…_-–")
    lead_m = LEAD_RE.match(body)
    lead, text = (
        (lead_m.group("lead") + lead_m.group("punct"), lead_m.group("rest"))
        if lead_m
        else ("", body)
    )
    para = ""
    m = PARA_TAIL_RE.match(text)
    if m:
        text, para = m.group("body"), m.group("para")
    if in_appendix:
        if not lead and para:
            lead = para  # OD: "5.1 113-114" with its title printed above and below
        elif not lead:
            m = APPENDIX_NO_TAIL_RE.match(text)
            if m:
                text, lead = m.group("body"), m.group("num")  # HP: "... PRIs 2 62"
        # The para column of an appendix list is the referring paragraph (BR "4.1 ... 4.1 137")
        if lead and not re.match(r"(?i)appendix|annexure", lead):
            lead = f"Appendix {lead}"
    elif para and not lead:
        lead = para
    # Keep a hyphen that splits a word over two lines ("2017-" / "22")
    return lead, re.sub(r"[\s.·…_]+$|\s+[-–]+$", "", text).strip(" .·…_")


def _split_by_gap(
    top_y: float,
    lines: List[Tuple[float, str]],
    bottom_y: float,
    lower_needs_title: bool,
) -> int:
    """
    Index splitting the lines between two rows: lines before it belong to the upper
    row, the rest to the lower one. Cells are separated by the widest vertical gap. On a
    tie (evenly spaced rows) the lines continue the upper title, unless the lower row
    has no title of its own; a line starting in lowercase or with a bracket always
    continues the line above it.
    """
    ys = [top_y] + [y for y, _ in lines] + [bottom_y]
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    widest = max(gaps)
    ties = [k for k, g in enumerate(gaps) if g >= widest - GAP_TIE]
    if not lower_needs_title:
        return ties[-1]
    for k in ties:
        if k == len(lines) or not (
            lines[k][1][:1].islower() or lines[k][1][:1] in "(["
        ):
            return k
    return ties[-1]


def _parse_rows(rows, state: Optional[dict] = None) -> List[Tuple[str, Optional[str]]]:
    """
    Return (title, printed_page) per entry of one contents page. Rows are (y, text), or
    plain strings (spaced evenly). Entries whose row has no page (a chapter heading
    above its sections) get page None.

    Handles the three-column Title | Para | Page layout: the para number becomes the
    leading section number ("Audit objectives 1.2 3" -> "1.2 Audit objectives"). Lines
    without a page are chapter or part headings (flushed as their own entry), or wrapped
    title lines, given to the row above or below across the wider vertical gap, so a
    vertically centred cell keeps its first and last lines. `state` carries the
    appendix block across contents pages.
    """
    state = state if state is not None else {}
    rows = [(float(i * 10), r) if isinstance(r, str) else r for i, r in enumerate(rows)]
    entries: List[_Entry] = []
    buffer: List[Tuple[float, str]] = []
    labels: List[str] = []
    anchor: Optional[_Entry] = None  # the entry the lines above the next row may join

    def give_buffer(lower: Optional[_Entry], lower_y: float) -> None:
        nonlocal buffer
        if not buffer:
            return
        if anchor is None:
            split = 0
        elif anchor.page is None and (lower is None or not lower.needs_title):
            # Heading lines continue until the first entry with a title
            split = len(buffer)
        elif lower is None:
            split = len(buffer)
        else:
            split = _split_by_gap(anchor.bottom_y, buffer, lower_y, lower.needs_title)
        if anchor is not None and split:
            anchor.suffix.extend(t for _, t in buffer[:split])
            anchor.bottom_y = buffer[split - 1][0]
        if lower is not None:
            lower.prefix = [t for _, t in buffer[split:]] + lower.prefix
        buffer = []

    for idx, (y, row) in enumerate(rows):
        row = row.strip()
        if not row or CONTENTS_HEADING_RE.match(row) or RUNNING_HEADER_RE.match(row):
            continue
        if row in state.get("repeated", ()):
            continue
        if _is_header_row(row):
            if "appendix" in row.lower() or "annexure" in row.lower():
                state["appendix"] = True
            continue
        if idx == len(rows) - 1 and re.fullmatch(r"\d{1,3}|" + ROMAN, row):
            continue  # the contents page's own page number
        if ANNEX_LABEL_RE.match(row):
            labels.append(row)
            continue
        match = None if CHAPTER_ONLY_RE.match(row) else PAGE_TAIL_RE.match(row)
        if match and _runs_backwards(match, entries):
            # "(SJH Road) ... in Package 3": a wrapped line ending in a number
            match = None
        if match is None and re.fullmatch(r"\d{1,3}|" + ROMAN, row) and buffer:
            # Page printed on its own row below a title
            match = re.match(r"(?P<body>)(?P<start>.+)", row)
        if match:
            lead, text = _parse_page_row(match, state.get("appendix", False))
            if labels and not lead:
                lead = labels.pop(0)
            labels = []
            entry = _Entry(
                y, lead, text, match.group("start"), state.get("appendix", False)
            )
            if not lead and not text and not buffer:
                continue
            if (
                not lead
                and anchor is not None
                and anchor.page is None
                and anchor is entries[-1]
                and is_chapter_title(anchor.text)
            ):
                # "Chapter 2: Tax Base of ... and" / "Co-operative Banks 9": a chapter title
                # wrapped onto the row with its page, not a chapter followed by a section
                anchor.suffix.extend([t for _, t in buffer] + [text])
                anchor.page, anchor.bottom_y, buffer = entry.page, y, []
                continue
            give_buffer(entry, y)
            entries.append(entry)
            anchor = entry
            title = entry.title()
            if APPENDIX_BLOCK_RE.match(title):
                state["appendix"] = True
            continue
        heading = APPENDIX_BLOCK_RE.match(row) or (
            not state.get("appendix")
            and (
                is_chapter_title(row)
                or (_is_caps(row) and (anchor is None or anchor.page is not None))
            )
        )
        if heading:
            give_buffer(None, y)
            entry = _Entry(y, "", row, None)
            entries.append(entry)
            anchor = entry
            if APPENDIX_BLOCK_RE.match(row):
                state["appendix"] = True
            elif is_chapter_title(row):
                state["appendix"] = False
            continue
        buffer.append((y, row))
        if sum(len(t) for _, t in buffer) > 250:  # prose, not a wrapped title
            buffer = []
    give_buffer(None, 0.0)
    for e in entries:
        # Page printed on its own row: the appendix number came in with the title lines
        if e.appendix and not e.lead and e.prefix and NUMBERED_RE.match(e.prefix[0]):
            e.lead = "Appendix"
    return [(e.title(), e.page) for e in entries if e.title()]


def _runs_backwards(match: "re.Match", entries: List["_Entry"]) -> bool:
    """A lead-less row continuing a title, whose trailing number is below the last page."""
    body = match.group("body").strip()
    if not body or not (body[:1].islower() or body[:1] in "(["):
        return False
    last = next((e.page for e in reversed(entries) if e.page), None)
    page = match.group("start")
    return bool(last and last.isdigit() and page.isdigit() and int(page) < int(last))


def _level(title: str, in_annexures: bool, in_chapter: bool) -> int:
    if is_chapter_title(title) or APPENDIX_BLOCK_RE.match(title):
        return 1
    if ANNEX_ITEM_RE.match(title):
        return 2 if in_annexures else 1
    if FRONT_BACK_RE.match(title):
        return 1
    numbered = NUMBERED_RE.match(title)
    if numbered:
        depth = numbered.group("num").count(".") + 1
        return min(depth, 4) if depth > 1 else (1 if not in_chapter else 2)
    return 2 if in_chapter or in_annexures else 1


# Page numbers are printed in the running header or footer. BR prints its footer 9.3%
# above the bottom edge, so the band is 10%; footnote markers inside it are dropped by
# the run checks below. Sideways numbers (landscape tables) sit up to 11% from the side
PAGE_NUMBER_BAND = 0.10
SIDE_NUMBER_BAND = 0.12
PAGE_NUMBER_RES = (
    # "12 | P a g e" (HP), "Page 12", "Page 12 of 90", "- 12 -", "12"
    re.compile(r"^(?P<n>\d{1,3})\s*\|\s*p\s*a\s*g\s*e$", re.IGNORECASE),
    re.compile(
        r"^p\s*a\s*g\s*e\s*\|?\s*(?P<n>\d{1,3})(?:\s+of\s+\d{1,4})?$", re.IGNORECASE
    ),
    re.compile(r"^[-–—]\s*(?P<n>\d{1,3})\s*[-–—]$"),
    re.compile(r"^(?P<n>\d{1,3})$"),
)
SHIFTED_DIGITS_RE = re.compile(r"^[\x13-\x1c]{1,3}$")
ROMAN_LABEL_RE = re.compile(r"^(?:[ivxlc]{1,7}|[IVXLC]{1,7})$")
# A kept label must share its offset (physical - printed) with another kept page this
# close. Two, not three: 2023_07 numbers two-page chapters between unnumbered dividers
RUN_WINDOW = 8
# Share of printed numbers a PDF's own page labels must match to be trusted elsewhere
PDF_LABEL_AGREEMENT = 0.95


def int_to_roman(value: int) -> str:
    out = ""
    for v, r in (
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ):
        while value >= v:
            out += r
            value -= v
    return out


def _label_value(label: str) -> Tuple[str, Optional[int]]:
    """("arabic" | "roman", value) of a printed page label."""
    if label.isdigit():
        return "arabic", int(label)
    value = roman_to_int(label)
    # Canonical numerals only: "ci", "lic" or "civil" are not page numbers
    if value and int_to_roman(value) == label.lower():
        return "roman", value
    return "roman", None


def _band_lines(page: fitz.Page) -> List[Tuple[float, str]]:
    """
    (distance from the page edge, text) of each line in the header/footer band. Lines
    set sideways (landscape tables on portrait pages) carry their page number at the
    side edge. Coordinates are in the unrotated page space, as is the dict's size.
    """
    data = page.get_text("dict")
    width, height = data.get("width") or 1, data.get("height") or 1
    out = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            if SHIFTED_DIGITS_RE.match(text):
                # Font-shifted footer (2023_19): digits sit 29 code points low
                text = unshift(text)
            x0, y0, x1, y1 = line["bbox"]
            dx, dy = line.get("dir", (1, 0))
            horizontal = abs(dx) >= abs(dy)
            lo, hi, size = (y0, y1, height) if horizontal else (x0, x1, width)
            band = PAGE_NUMBER_BAND if horizontal else SIDE_NUMBER_BAND
            pos = (lo + hi) / 2 / size
            if pos <= band:
                out.append((lo / size, text))
            elif pos >= 1 - band:
                out.append((1 - hi / size, text))
    return out


def _page_number_candidates(page: fitz.Page) -> List[Tuple[str, int, str, float]]:
    """(kind, value, label, edge distance) for each band line that reads as a page number."""
    found = []
    for edge, text in _band_lines(page):
        for pattern in PAGE_NUMBER_RES:
            m = pattern.match(text)
            if m:
                value = int(m.group("n"))
                if value:
                    found.append(("arabic", value, str(value), edge))
                break
        else:
            if ROMAN_LABEL_RE.match(text):
                kind, value = _label_value(text)
                if value:
                    found.append((kind, value, text, edge))
    return found


def _longest_run_chain(
    cands: List[Tuple[int, int, str, float]],
) -> List[Tuple[int, int, str]]:
    """
    Largest set of (page, value) candidates, one per page, in which the printed number
    rises with the page and the offset never shrinks (unnumbered pages only add to it).
    Footnote markers and table cells break this order, so they drop out.
    """
    cands = sorted(cands)
    best: List[float] = []
    prev: List[int] = []
    for k, (page, value, _, edge) in enumerate(cands):
        # Nearer the page edge wins a tie (a footnote marker sits above the page number)
        weight = 1 - min(edge, 0.5) / 10
        best.append(weight)
        prev.append(-1)
        for j in range(k):
            pj, vj = cands[j][0], cands[j][1]
            if (
                pj < page
                and vj < value
                and page - pj >= value - vj
                and best[j] + weight > best[k]
            ):
                best[k], prev[k] = best[j] + weight, j
    if not best:
        return []
    k = max(range(len(best)), key=best.__getitem__)
    chain = []
    while k >= 0:
        chain.append(cands[k][:3])
        k = prev[k]
    return chain[::-1]


def _kept_in_runs(
    chain: List[Tuple[int, int, str]], lone_before: int = -1
) -> List[Tuple[int, int, str, int]]:
    """
    Chain members whose offset another member within RUN_WINDOW pages shares, plus lone
    pages that step evenly from a chain neighbour: pinned between two (107 and 109 around
    it: only 108 fits), or front matter printed on rectos only, with unnumbered blank
    versos ("i" on page 6, "iii" on page 10). Pages before `lone_before` are kept even
    alone (a one-page roman Preface ahead of the arabic numbering). Returns (page, value,
    label, run length).
    """
    kept = []
    for k, (page, value, label) in enumerate(chain):
        run = sum(
            1
            for p, v, _ in chain
            if p - v == page - value and abs(p - page) <= RUN_WINDOW
        )
        if run < 2 and 0 < k < len(chain) - 1:
            (pa, va, _), (pb, vb, _) = chain[k - 1], chain[k + 1]
            if vb - va == 2 and pb - pa <= RUN_WINDOW:
                run = 2
        if run < 2:
            for j in (k - 1, k + 1):
                if 0 <= j < len(chain):
                    dp, dv = abs(chain[j][0] - page), abs(chain[j][1] - value)
                    if dp <= RUN_WINDOW and dv <= dp <= 2 * dv + 1:
                        run = 2
        if run >= 2 or page < lone_before:
            kept.append((page, value, label, run))
    return kept


def build_printed_page_map(doc: fitz.Document) -> Dict[int, str]:
    """
    Page number printed on each physical page ({physical: label}), for detected pages
    only. Arabic labels are digits; roman labels keep their numerals and case.

    Read from the header/footer band: plain numbers, "N | P a g e", "Page N (of M)",
    "- N -" and roman front-matter numerals. Each numbering is taken as a rising
    sequence (a second one may restart before or after the first: a preface numbered
    ii-iv ahead of the main front matter), and a label is kept only if a nearby page
    shares its offset. The offset is not constant: blank pages and unnumbered full-page
    tables shift it.
    """
    by_kind: Dict[str, List[Tuple[int, int, str, float]]] = {"arabic": [], "roman": []}
    for i in range(doc.page_count):
        for kind, value, label, edge in _page_number_candidates(doc[i]):
            by_kind[kind].append((i, value, label, edge))

    labels: Dict[int, str] = {}
    support: Dict[int, int] = {}
    for kind in ("arabic", "roman"):
        cands = by_kind[kind]
        # Roman front matter ends where the arabic numbering starts
        lone_before = min(labels, default=-1) if kind == "roman" else -1
        while cands:
            chain = _longest_run_chain(cands)
            kept = _kept_in_runs(chain, lone_before)
            if not kept:
                break
            for page, _, label, run in kept:
                # A page with both numberings keeps the one with the longer run
                if run > support.get(page, 0):
                    labels[page], support[page] = label, run
            first, last = chain[0][0], chain[-1][0]
            cands = [c for c in cands if c[0] < first or c[0] > last]
    return labels


def _split_labels(labels: Dict[int, str]) -> Tuple[Dict[int, int], Dict[int, int]]:
    """{physical: arabic number} and {physical: roman value} from a page map."""
    arabic: Dict[int, int] = {}
    roman: Dict[int, int] = {}
    for i, label in labels.items():
        kind, value = _label_value(label)
        if value:
            (arabic if kind == "arabic" else roman)[i] = value
    return arabic, roman


def interpolate_page_labels(
    labels: Dict[int, str], page_count: int
) -> Dict[int, Optional[str]]:
    """
    Logical page label of every physical page: the detected label, else a label
    interpolated between the nearest detected pages before and after when both have the
    same kind and offset (an unbroken run), else None. Never physical + 1.
    """
    out: Dict[int, Optional[str]] = {i: labels.get(i) for i in range(page_count)}
    known = sorted(i for i in labels if 0 <= i < page_count)
    for a, b in zip(known, known[1:]):
        if b - a < 2:
            continue
        kind_a, value_a = _label_value(labels[a])
        kind_b, value_b = _label_value(labels[b])
        if not value_a or kind_a != kind_b or b - value_b != a - value_a:
            continue
        for i in range(a + 1, b):
            value = value_a + (i - a)
            if kind_a == "arabic":
                out[i] = str(value)
            else:
                numeral = int_to_roman(value)
                out[i] = numeral.upper() if labels[a].isupper() else numeral
    return out


def logical_page_labels(doc: fitz.Document) -> Dict[int, Optional[str]]:
    """
    Logical page label of every physical page: the printed page number (interpolated
    inside a run), else the PDF's own page label when those labels agree with the
    printed numbers, else None. Printed numbers come first: BR's PDF labels call
    printed pages 2-15 "xx"-"xxxiii".
    """
    printed = build_printed_page_map(doc)
    labels = interpolate_page_labels(printed, doc.page_count)
    pdf_labels = {i: doc[i].get_label() or None for i in range(doc.page_count)}
    checked = [i for i in printed if pdf_labels[i]]
    if checked and sum(
        pdf_labels[i] == printed[i] for i in checked
    ) >= PDF_LABEL_AGREEMENT * len(checked):
        for i, label in labels.items():
            if label is None:
                labels[i] = pdf_labels[i]
    return labels


def _to_physical(
    printed: int, labels: Dict[int, int], min_page: int
) -> Tuple[Optional[int], bool]:
    """
    Physical page printed with this number, interpolated from the nearest labelled page
    when no page carries it. Returns (page, exact_label_match).
    """
    exact = sorted(
        i for i, label in labels.items() if label == printed and i >= min_page
    )
    if exact:
        return exact[0], True
    below = [
        (i, label) for i, label in labels.items() if label < printed and i >= min_page
    ]
    if below:
        i, label = max(below, key=lambda x: x[1])
        return i + (printed - label), False
    above = [
        (i, label) for i, label in labels.items() if label > printed and i >= min_page
    ]
    if above:
        i, label = min(above, key=lambda x: x[1])
        return i - (label - printed), False
    return None, False


def parse_printed_toc(
    doc: fitz.Document, report_id: str = "unknown"
) -> Tuple[List[List], float]:
    """
    Parse the printed contents page(s).

    Returns:
        ([[level, title, physical_page], ...], confidence 0-1). Confidence is the share of
        entries whose title is actually found on (or next to) the mapped page.
    """
    start = _find_contents_start(doc)
    if start is None:
        return [], 0.0

    pages = list(range(start, min(start + 8, doc.page_count)))
    page_rows = {i: _page_rows_y(doc[i]) for i in pages}
    # Running and column headers repeated on continuation pages ("Audit Report (Local
    # Government) for the year ended March 2022"); an entry row never repeats exactly
    edges = {i: {t for _, t in page_rows[i][:5] + page_rows[i][-2:]} for i in pages}
    seen = Counter(text for i in pages for text in edges[i])
    state = {"repeated": {text for text, n in seen.items() if n >= 2}}

    raw_entries: List[Tuple[str, Optional[str]]] = []
    contents_end = start
    for i in pages:
        page_entries = _parse_rows(page_rows[i], state)
        if i > start and len(page_entries) < 3:
            break
        raw_entries.extend(page_entries)
        contents_end = i

    if len(raw_entries) < 3:
        return [], 0.0

    arabic, roman = _split_labels(build_printed_page_map(doc))
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
                    in_chapter = is_chapter_title(title)
                    in_annexures = bool(APPENDIX_BLOCK_RE.match(title))
                toc.append([level, title, physical])
            continue
        # Page numbers listed on the contents pages must not label those pages
        if printed.isdigit():
            physical, exact = _to_physical(int(printed), arabic, contents_end + 1)
        else:
            value = roman_to_int(printed)
            physical, exact = (
                _to_physical(value, roman, contents_end + 1) if value else (None, False)
            )
        if physical is None or not 0 <= physical < doc.page_count:
            continue
        level = _level(title, in_annexures, in_chapter)
        if level == 1:
            in_chapter = is_chapter_title(title)
            in_annexures = bool(APPENDIX_BLOCK_RE.match(title))
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
    for _, printed in entries[idx + 1 :]:
        if printed is not None:
            return _printed_to_physical(printed, arabic, roman, contents_end + 1)
    return None


def _find_title_page(
    doc: fitz.Document, title: str, first: int, last: Optional[int]
) -> Optional[int]:
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
            cache[i] = (
                _normalize(repair_font_shift(doc[i].get_text("text")))
                if 0 <= i < doc.page_count
                else ""
            )
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


PART_ROW_RE = re.compile(r"^\s*PART\s*[-–:.]?\s*[A-Z]\b", re.IGNORECASE)


def fold_part_rows(toc: List[List]) -> List[List]:
    """
    Drop "PART-A …" grouping rows that sit on the page of the chapter they introduce.
    They come out as L1 entries next to that chapter, and one of the two becomes an
    empty parent (ATIRs: PART-A = PRIs, PART-B = ULBs; the chapter titles say so too).
    """
    out = []
    for i, entry in enumerate(toc):
        if PART_ROW_RE.match(str(entry[1])):
            near = [e for e in toc[max(0, i - 2): i + 3] if e is not entry and abs(e[2] - entry[2]) <= 1]
            if any(is_chapter_title(str(e[1])) for e in near):
                continue
        out.append(entry)
    return out
