"""
TOC quality score (0-100) from content, not just shape.

The previous score gave any TOC with 10+ entries, 3 levels and ascending pages ~85-100,
so PDF-merger bookmarks ("Blank Page", "Binder1.pdf", "5 Chapter 1 HP ATIR"), finding
sentences promoted to headings and split chapter banners all scored 100. This score
starts at 100 and deducts for each defect found; `score_toc` returns the breakdown.

The title predicates (`is_junk_title`, `is_sentence_like`, `is_garbage_title`) are shared
with bookmark filtering, TOC normalisation and the preflight garbage-title check, so
that every stage agrees on what is not a heading.
"""

import re
from typing import Dict, List, Optional

from src.parsing_pipeline.extractors.text_repair import is_reversed
from src.parsing_pipeline.modules.printed_toc_parser import (
    CHAPTER_ONLY_RE,
    FRONT_BACK_RE,
    _verify_on_pages,
    is_chapter_title,
)

CHAPTER_NUM_RE = re.compile(r"^\s*chapter\s*[-–—:]?\s*([ivxlc]+|\d+)\b", re.IGNORECASE)
# Chapter number of an L1 title: "Chapter-2 ...", "III AN OVERVIEW ..." (BR), "2 Mandate ..."
L1_NUMBER_RE = re.compile(
    r"^\s*(?:chapter\s*[-–—:]?\s*(?P<a>[ivxlc]+|\d+)\b|(?P<r>[IVX]{1,4})\s+[A-Z]{2}|(?P<n>\d{1,2})\.?\s+[A-Z])",
    re.IGNORECASE,
)
SECTION_LEAD_RE = re.compile(r"^\s*(?P<chapter>\d+)\.\d+")
# A part of a combined report: chapter numbers restart in each ("PART II – ECONOMIC
# SERVICES" / "CHAPTER-I : GENERAL", KL)
PART_TITLE_RE = re.compile(
    r"^\s*part\s*[-–—:.]?\s*([ivxlc]+|\d+|[a-z])\b", re.IGNORECASE
)
SECTION_NUM_RE = re.compile(r"^\s*\d+\.\d+")
SHIFTED_SIGNATURE_RE = re.compile(r"&[A-Z]{3}|\$[A-Z]{3}|[A-Z]{2,}\\")
MAX_L1 = 35
CROSS_REFERENCE_RE = re.compile(
    r"^\(\s*(para|paragraph|refer|reference|source|₹|rs\.|amount|figures)",
    re.IGNORECASE,
)
ENUMERATOR_RE = re.compile(r"^\s*(\(?[ivxlc]{1,5}[.)]|\(?[a-zA-Z][.)]|\(\d+\))\s+")

# PDF-merger and file-name bookmarks (A-4-02)
JUNK_TITLE_RE = re.compile(
    r"^blank\s+page$|\.pdf$|^page\s+\d+$|^binder\d*|\bcover\b|separator|inner\s+head|"
    r"back\s+page|front\s+page|_english|english_",
    re.IGNORECASE,
)
# File-order prefix of a merged file's bookmark: "2 TOC", "5 Chapter 1 HP ATIR",
# "6.Chapter 1-Introduction", "02_Index", "10. Appendix Median"
FILE_ORDER_RE = re.compile(r"^(?P<n>\d{1,2})\s*[._-]?\s*(?P<rest>[A-Za-z].*)$")
FILE_ORDER_TARGET_RE = re.compile(
    r"^(chapter|appendix|appendices|annex|preface|overview|overiew|executive\s+summary|glossary|"
    r"table\s+of\s+contents|contents|toc|index|cover|separator|blank)\b",
    re.IGNORECASE,
)
SECTION_LABEL_RE = re.compile(
    r"^\s*(\d+(\.\d+)+|(appendix|annexure)[\s-]*[\w.]+)\s*[.:]?\s+", re.IGNORECASE
)
RECOMMENDATION_BOX_RE = re.compile(
    r"^recommendation\s*(no\.?\s*)?(\d|[:\-–])", re.IGNORECASE
)
AMOUNT_RE = re.compile(r"[₹`]\s*\d")
QUOTE_START = "\"'“‘”’"
# Table rows taken for headings: "Sl. No", "(` in lakh)", "Total (iii) 1,00,000 4. Sh. ..."
TABLE_ROW_RE = re.compile(
    r"\bsl\.?\s*no\b|\(\s*[₹`]\s*in\s+(lakh|crore)", re.IGNORECASE
)
GROUPED_NUMBER_RE = re.compile(r"(?<![₹`\d,.])\s?\d{1,3}(?:,\d{2,3})+(?![\d,])")
# Para number left inside a title ("Audit objectives 1.2"), not a date or an amount
PARA_INSIDE_RE = re.compile(
    r"(?<!appendix)(?<!annexure)\s\d{1,2}(?:\.\d{1,2})+(?![\d.,%])", re.IGNORECASE
)
SINGLE_DIGIT_PER_CENT = re.compile(r"\d\s*(per\s*cent|%)", re.IGNORECASE)

# Acceptance threshold used by the scaffolding (`bookmark_quality_threshold` * 100)
ACCEPT_THRESHOLD = 60


def _roman(text: str) -> int:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    for i, c in enumerate(text.lower()):
        v = values.get(c, 0)
        total += (
            -v if i + 1 < len(text) and values.get(text[i + 1].lower(), 0) > v else v
        )
    return total


def is_junk_title(title: str) -> bool:
    """PDF-merger or file-name bookmark: "Blank Page", "Binder1.pdf", "2 TOC", "01_Cover"."""
    t = (title or "").strip()
    if JUNK_TITLE_RE.search(t):
        return True
    m = FILE_ORDER_RE.match(t)
    if m:
        rest = m.group("rest")
        # "5 Chapter 1 HP ATIR", "3 Preface", "02_Index": a file number before a part name
        if FILE_ORDER_TARGET_RE.match(rest) or "_" in t or re.match(r"^0\d", t):
            return True
    return "_" in t and " " not in t.strip("_")


def _body(title: str) -> str:
    """Title without its leading section number or appendix label."""
    return SECTION_LABEL_RE.sub("", title, count=1).strip()


def is_sentence_like(title: str) -> bool:
    """
    A sentence, list item or recommendation box, not a heading: too long, ends with a
    full stop, quotes an amount, opens with a list marker or quote, or "Recommendation".
    Numbered contents entries (section numbers, appendices) may run longer and carry an
    amount: "4.1.2.5 Additional discounts of ₹ 41.77 crore ..." is a printed section.
    """
    t = (title or "").strip()
    if not t:
        return False
    numbered = bool(SECTION_LABEL_RE.match(t))
    body = _body(t)
    words = len(body.split())
    # Appendix titles are table captions and run long (HP's Appendix 5 has 39 words)
    appendix = bool(re.match(r"(?i)appendix|annexure", t))
    # Chapter titles run long too: "CHAPTER I An Overview of the Functioning,
    # Accountability Mechanism and Financial Reporting Issues of ..." (19 words)
    chapter = bool(re.match(r"(?i)chapter\b", t))
    if not appendix and words > (30 if numbered or chapter else 14):
        return True
    if body.endswith(".") and words > 5 and not body.endswith("etc."):
        return True
    if not numbered and AMOUNT_RE.search(t):
        return True
    # A list item opening a sentence; short ones ("a) Tendering procedure", "i. Direct
    # Taxes") are sub-headings
    if ENUMERATOR_RE.match(t) and (
        len(ENUMERATOR_RE.sub("", t).split()) > 10 or body.endswith(".")
    ):
        return True
    if t[0] in QUOTE_START:
        return True
    # A recommendation box ("Recommendation 3.1", "Recommendation No. 9"), not a section
    # about one ("3.8.3 Recommendation of the 15th Finance Commission")
    return bool(RECOMMENDATION_BOX_RE.match(t))


def is_table_row(title: str) -> bool:
    """
    A table header or data row taken for a heading. A grouped number counts only in an
    unnumbered title without a currency sign: "3.6.12.1 ... ₹ 1,902.05 crore" is a section.
    """
    t = title or ""
    if TABLE_ROW_RE.search(t):
        return True
    return (
        not SECTION_LABEL_RE.match(t)
        and not AMOUNT_RE.search(t)
        and bool(GROUPED_NUMBER_RE.search(t))
    )


def _is_fragment(title: str) -> bool:
    """Garbage by form: fragments, cross-references, encoding garbage, number rows."""
    t = (title or "").strip()
    limit = 300 if re.match(r"(?i)appendix|annexure", t) else 160
    if len(t) < 3 or len(t) > limit:
        return True
    # List enumerators ("i.", "(a)", "b)") are fine; the text after them must start a heading
    body = ENUMERATOR_RE.sub("", t) or t
    if body[0].islower() or body[0] in "|*•-=":
        return True
    # Cross-references and notes: "(Para 3.1 and 3.2)", "(Refer Annexure 2)", "(₹ in crore)"
    if CROSS_REFERENCE_RE.match(t) or (t.startswith("(") and t.endswith(")")):
        return True
    if SHIFTED_SIGNATURE_RE.search(t) or is_reversed(t):
        return True
    letters = sum(c.isalpha() for c in t)
    return letters < 0.5 * len(t.replace(" ", ""))


def is_garbage_title(title: str) -> bool:
    """
    Titles that are not headings: fragments, table rows, encoding garbage, merger-junk
    bookmarks and sentences. Drives TOC normalisation and the preflight garbage check.
    """
    t = str(title or "")
    return _is_fragment(t) or is_junk_title(t) or is_sentence_like(t) or is_table_row(t)


def chapter_numbers(toc: List[List]) -> List[int]:
    nums = []
    for level, title, _ in toc:
        m = CHAPTER_NUM_RE.match(str(title))
        if m and level == 1:
            token = m.group(1)
            nums.append(int(token) if token.isdigit() else _roman(token))
    return nums


def _l1_number(title: str) -> Optional[int]:
    m = L1_NUMBER_RE.match(title)
    if not m:
        return None
    token = m.group("a") or m.group("r") or m.group("n")
    return int(token) if token.isdigit() else _roman(token)


def _is_split_fragment(title: str) -> bool:
    """A chapter label without its title, or one stray word of a split banner."""
    t = title.strip()
    if CHAPTER_ONLY_RE.match(t):
        return True
    return (
        len(t.split()) == 1
        and not FRONT_BACK_RE.match(t)
        and not re.match(r"^[\d.]+$", t)
    )


def _is_merged(title: str) -> bool:
    """A chapter merged with its first section, or a para number left inside the title."""
    if is_chapter_title(title) and re.search(r"\b\d+\.\d+\b", title):
        return True
    rest = re.sub(r"^\S+\s", "", title)
    return bool(PARA_INSIDE_RE.search(rest)) and not SINGLE_DIGIT_PER_CENT.search(rest)


def score_toc(toc: List[List], total_pages: int = 0, doc=None) -> Dict:
    """
    Score a [[level, title, page], ...] TOC from 0 (unusable) to 100.

    Returns {"score": int, "deductions": {name: points}, "counts": {name: n}}. With a
    document (`doc`, a fitz.Document, pages 0-based), also checks that each title is
    found on its page ±1.
    """
    if not toc:
        return {"score": 0, "deductions": {"empty": 100}, "counts": {"entries": 0}}

    n = len(toc)
    titles = [str(e[1]) for e in toc]
    deductions: Dict[str, float] = {}
    counts: Dict[str, float] = {"entries": n}

    def deduct(name: str, points: float) -> None:
        if points > 0:
            deductions[name] = round(points, 1)

    if n < 5:
        deduct("too_few_entries", 40)

    junk = [is_junk_title(t) for t in titles]
    sentence = [not j and is_sentence_like(t) for t, j in zip(titles, junk)]
    table = [
        not j and not s and is_table_row(t) for t, j, s in zip(titles, junk, sentence)
    ]
    other = [
        not (j or s or r) and _is_fragment(t)
        for t, j, s, r in zip(titles, junk, sentence, table)
    ]
    split = [_is_split_fragment(t) for t in titles]
    counts.update(
        junk=sum(junk),
        sentence_like=sum(sentence),
        table_rows=sum(table),
        fragments=sum(other),
        split_headings=sum(split),
    )
    deduct("junk_titles", 80 * sum(junk) / n)
    deduct("sentence_like", 60 * sum(sentence) / n)
    deduct("table_rows", 60 * sum(table) / n)
    deduct("garbage_titles", 60 * sum(other) / n)
    deduct("split_headings", 60 * sum(split) / n)

    l1 = [e for e in toc if e[0] == 1]
    if len(l1) > MAX_L1:
        deduct("too_many_l1", 20)
    if l1:
        # Numbered sections ("1.3 ...") at chapter level mean levels were not detected
        sections_at_l1 = sum(1 for e in l1 if SECTION_NUM_RE.match(str(e[1])))
        deduct("sections_at_l1", 40 * sections_at_l1 / len(l1))
        # A chapter banner split into several L1 entries lands them on one page; a
        # part title printed above its first chapter does not count
        same_page = sum(
            1
            for a, b in zip(l1, l1[1:])
            if a[2] == b[2] and not PART_TITLE_RE.match(str(a[1]))
        )
        counts["l1_same_page"] = same_page
        deduct("l1_same_page", 40 * same_page / len(l1))

    nums = chapter_numbers(toc)
    if nums:
        missing = len(set(range(1, max(nums) + 1)) - set(nums))
        deduct("missing_chapters", min(30, 10 * missing))
    duplicates, seen = 0, set()
    for e in l1:
        if PART_TITLE_RE.match(str(e[1])):
            seen = set()
            continue
        number = _l1_number(str(e[1]))
        if number is not None:
            duplicates += number in seen
            seen.add(number)
    counts["duplicate_chapters"] = duplicates
    deduct("duplicate_chapters", min(30, 10 * duplicates))

    merged = sum(1 for t in titles if _is_merged(t))
    counts["merged_or_para_in_title"] = merged
    deduct("merged_or_para_in_title", 40 * merged / n)

    # Sections must sit under their own chapter: "2.3" under Chapter 2
    chapter, checked, mismatched = None, 0, 0
    for level, title, _ in toc:
        if level == 1:
            chapter = _l1_number(str(title))
            continue
        m = SECTION_LEAD_RE.match(str(title))
        if chapter is not None and m:
            checked += 1
            mismatched += int(m.group("chapter")) != chapter
    counts["section_chapter_mismatch"] = mismatched
    if checked:
        deduct("section_chapter_mismatch", 30 * mismatched / checked)

    pages = [e[2] for e in toc]
    if len(pages) > 1:
        backwards = sum(1 for a, b in zip(pages, pages[1:]) if b < a)
        deduct("backwards_pages", 30 * backwards / (len(pages) - 1))

    if total_pages:
        density = n / total_pages
        counts["entries_per_page"] = round(density, 2)
        if density > 1.2:
            deduct("density", min(30, 25 * (density - 1.2)))
        if pages and max(pages) < 0.5 * total_pages:
            deduct("stops_halfway", 15)  # TOC stops halfway through the document

    if doc is not None:
        verified = _verify_on_pages(doc, [list(e) for e in toc], set())
        counts["verified"] = round(verified, 2)
        deduct("unverified", 50 * (1 - verified))

    score = max(0, min(100, int(round(100 - sum(deductions.values())))))
    return {"score": score, "deductions": deductions, "counts": counts}


def assess_toc_quality(toc: List[List], total_pages: int = 0, doc=None) -> int:
    """Score a [[level, title, page], ...] TOC from 0 (unusable) to 100 (see `score_toc`)."""
    return score_toc(toc, total_pages, doc)["score"]


def junk_share(toc: List[List]) -> float:
    """Share of entries that are merger-junk bookmarks (for rejecting a bookmark set)."""
    return sum(is_junk_title(str(e[1])) for e in toc) / len(toc) if toc else 0.0


def _title_key(title: str) -> str:
    """Comparable form of a title: no chapter/section label, letters and digits only."""
    body = re.sub(
        r"^\s*(chapter|part)\s*[-–—:.]?\s*([ivxlc]+|\d+)\b", "", title, flags=re.I
    )
    body = re.sub(r"^\s*[\d.]+\s*[.:]?\s*", "", body)
    return re.sub(r"[^a-z0-9]+", "", body.lower())[:25]


def chapter_agreement(reference: List[List], candidate: List[List]) -> float:
    """
    Share of the reference TOC's chapter titles (L1 chapters, or every L1 when none is
    numbered as a chapter) found among the candidate's titles. Lets a richer bookmark
    set win over a chapters-only printed contents page only when they agree (A-4-02).
    """
    l1 = [str(e[1]) for e in reference if e[0] == 1]
    chapters = [t for t in l1 if is_chapter_title(t)] or l1
    keys = [k for k in (_title_key(t) for t in chapters) if k]
    if not keys:
        return 0.0
    found = {_title_key(str(e[1])) for e in candidate}
    return sum(any(k and (k in f or f in k) for f in found if f) for k in keys) / len(
        keys
    )
