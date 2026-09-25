"""
TOC quality score (0-100) from content, not just shape.

The previous score gave any TOC with 10+ entries, 3 levels and ascending pages ~85-100,
so garbage chapter titles, sections promoted to chapters and missing chapters never
reached Phase 5.7. This score starts at 100 and deducts for each defect found.
"""

import re
from typing import List

from src.parsing_pipeline.extractors.text_repair import is_reversed

CHAPTER_NUM_RE = re.compile(r"^\s*chapter\s*[-:]?\s*([ivxlc]+|\d+)\b", re.IGNORECASE)
SECTION_NUM_RE = re.compile(r"^\s*\d+\.\d+")
SHIFTED_SIGNATURE_RE = re.compile(r"&[A-Z]{3}|\$[A-Z]{3}|[A-Z]{2,}\\")
MAX_L1 = 35
CROSS_REFERENCE_RE = re.compile(r"^\(\s*(para|paragraph|refer|reference|source|₹|rs\.|amount|figures)", re.IGNORECASE)
ENUMERATOR_RE = re.compile(r"^\s*(\(?[ivxlc]{1,5}[.)]|\(?[a-zA-Z][.)]|\(\d+\))\s+")


def _roman(text: str) -> int:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    for i, c in enumerate(text.lower()):
        v = values.get(c, 0)
        total += -v if i + 1 < len(text) and values.get(text[i + 1].lower(), 0) > v else v
    return total


def is_garbage_title(title: str) -> bool:
    """Titles that are not headings: fragments, table rows, encoding garbage."""
    t = (title or "").strip()
    if len(t) < 3 or len(t) > 160:
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


def chapter_numbers(toc: List[List]) -> List[int]:
    nums = []
    for level, title, _ in toc:
        m = CHAPTER_NUM_RE.match(str(title))
        if m and level == 1:
            token = m.group(1)
            nums.append(int(token) if token.isdigit() else _roman(token))
    return nums


def assess_toc_quality(toc: List[List], total_pages: int = 0) -> int:
    """Score a [[level, title, page], ...] TOC from 0 (unusable) to 100."""
    if not toc:
        return 0

    score = 100.0
    n = len(toc)
    if n < 5:
        score -= 40

    garbage = sum(1 for _, title, _ in toc if is_garbage_title(str(title)))
    score -= 60 * garbage / n

    l1 = [e for e in toc if e[0] == 1]
    if len(l1) > MAX_L1:
        score -= 20
    if l1:
        # Numbered sections ("1.3 ...") at chapter level mean levels were not detected
        sections_at_l1 = sum(1 for e in l1 if SECTION_NUM_RE.match(str(e[1])))
        score -= 40 * sections_at_l1 / len(l1)

    nums = sorted(set(chapter_numbers(toc)))
    if nums:
        missing = len(set(range(1, max(nums) + 1)) - set(nums))
        score -= min(30, 10 * missing)

    pages = [e[2] for e in toc]
    if len(pages) > 1:
        backwards = sum(1 for a, b in zip(pages, pages[1:]) if b < a)
        score -= 30 * backwards / (len(pages) - 1)

    if total_pages and pages and max(pages) < 0.5 * total_pages:
        score -= 15  # TOC stops halfway through the document

    return max(0, min(100, int(round(score))))
