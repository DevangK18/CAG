"""
Caption, unit and source/note lines around tables and figures.

CAG reports print a caption ("Table 3.2: Details of grants", "Chart 1.1: …") above
or below a table or figure, a unit line ("(₹ in crore)") above a table, and source
or note lines below it. Phase 6 attaches these to their table or figure instead of
keeping them as tiny separate chunks.
"""

import re
from typing import List, Optional, Tuple

CAPTION_RE = re.compile(
    r"^\s*(?P<kind>Table|Chart|Figure|Fig\.|Graph|Statement|Exhibit|Box|Map|Picture|"
    r"Photograph|Photo|Diagram|Image|Appendix|Annexure|Annex)\s*(?:No\.?)?\s*[-–:.]?\s*"
    r"(?P<number>(?:\d+|[IVX]+)(?:\s*[.\-–]\s*\d+)*(?:\s*\([a-z]\))?)(?![\d])",
    re.IGNORECASE,
)

# An appendix or annexure heading printed over its table. Its number is not a table
# number ("Appendix 4.3" is not "Table 4.3")
APPENDIX_KINDS = {"appendix", "annexure", "annex"}

# The cross-reference line under an appendix heading: "(Reference: Paragraph 4.3/Page 27)",
# "(Refer paragraph 2.1.1)", "(Reference Paragraph: 4.1.3.1)"
REFERENCE_LINE_RE = re.compile(
    r"^\s*\(?\s*(?:Reference|Refer|Ref\.?)\b[^()]{0,80}\)?\s*$", re.IGNORECASE
)

# A caption repeated on a continuation page: "Appendix 4.3 (contd.)", "(concld.)"
CONTINUED_RE = re.compile(r"\b(?:contd|continued|concld|concluded)\b\.?", re.IGNORECASE)

UNIT_LINE_RE = re.compile(
    r"^\s*\(?\s*(?:(?:All\s+)?(?:Figures?|Amounts?)\s*:?\s+(?:are\s+)?)?(?:in\s+)?"
    r"(?:₹|`|Rs\.?|INR|Rupees)\s*(?:in\s+)?"
    r"(?P<unit>lakh\s+crore|crore|lakh|thousand|million|billion)?\s*\)?\s*$",
    re.IGNORECASE,
)

# Any unit line, money or not: "(unit: kg/tonne of hot metal)", "(Qty in million
# tonne)", "(Amount: ₹ in crore)", "(In per cent)", "(Figures in number)"
ANY_UNIT_LINE_RE = re.compile(
    r"^\s*\(\s*(?!source|note)(?:"
    r"(?:unit|units|amount|amounts|figures?|qty|quantity|values?|all\s+figures)\b[^()]{0,60}"
    r"|[^()]{0,40}\b(?:in|unit|units)\b[^()]{0,40}"
    r")\)\s*$",
    re.IGNORECASE,
)

SOURCE_NOTE_RE = re.compile(
    r"^\s*\(?\s*(?:Source|Sources|Note|Notes|Data\s+source)\s*[:\-–]", re.IGNORECASE
)

TABLE_KINDS = {"table", "statement", *APPENDIX_KINDS}
FIGURE_KINDS = {
    "chart",
    "figure",
    "fig.",
    "graph",
    "exhibit",
    "map",
    "picture",
    "photograph",
    "photo",
    "diagram",
    "image",
    "box",
}


def parse_caption(text: str) -> Optional[dict]:
    """{"kind", "number", "text"} when text starts like a caption, else None."""
    if not text or len(text) > 400:
        return None
    m = CAPTION_RE.match(text)
    if not m:
        return None
    number = re.sub(r"\s+", "", m.group("number")).replace("–", "-")
    kind = m.group("kind").lower()
    return {
        "kind": kind,
        "number": None if kind in APPENDIX_KINDS else number,
        "label": f"{kind} {number.lstrip('-')}",
        "text": " ".join(text.split()),
    }


def unit_of(text: str) -> Optional[str]:
    """'(₹ in crore)' -> '₹ in crore'; None when text is not a unit line."""
    if not text or len(text) > 40:
        return None
    m = UNIT_LINE_RE.match(text)
    if not m or not m.group("unit"):
        return None
    return f"₹ in {m.group('unit').lower()}"


def is_source_note(text: str) -> bool:
    return bool(text) and bool(SOURCE_NOTE_RE.match(text))


def is_unit_line(text: str) -> bool:
    """A short unit line above a table or chart, money or not."""
    return (
        bool(text)
        and len(text) <= 70
        and (unit_of(text) is not None or bool(ANY_UNIT_LINE_RE.match(text)))
    )


# A table note marked with a symbol: "* Includes ₹ 4,580.61 crore …", "$ Borrowings …"
TABLE_NOTE_RE = re.compile(r"^\s*[*$#&@†‡]+\s*\S")


def is_table_note(text: str) -> bool:
    return bool(text) and bool(TABLE_NOTE_RE.match(text))


def is_reference_line(text: str) -> bool:
    return bool(text) and bool(REFERENCE_LINE_RE.match(text))


def is_continued_caption(text: str) -> bool:
    """A caption marked as a continuation ("Appendix 4.3 (contd.)")."""
    return bool(text) and bool(CONTINUED_RE.search(text))


def appendix_caption_above(texts: List[str]) -> Optional[Tuple[int, str]]:
    """
    An appendix caption separated from its table by a reference line and a title.

    CAG appendices print "Appendix 4.3", "(Reference: Paragraph 4.3/Page 27)" and a
    title ("Statement showing …") above the table, often as separate blocks. texts are
    the blocks above the table, nearest first. Returns (blocks used, caption in reading
    order), or None when no appendix caption sits within a title and a reference line.
    """
    between: List[str] = []
    titles = 0
    for count, text in enumerate(texts[:3], start=1):
        text = " ".join((text or "").split())
        parsed = parse_caption(text)
        if parsed and parsed["kind"] in APPENDIX_KINDS:
            if not between:
                return None  # directly above: the plain caption rule takes it
            return count, " ".join([text] + between[::-1])
        if is_reference_line(text):
            between.append(text)
            continue
        if (
            titles
            or parsed
            or not text
            or len(text) > 300
            or is_unit_line(text)
            or is_source_note(text)
        ):
            return None
        titles += 1
        between.append(text)
    return None
