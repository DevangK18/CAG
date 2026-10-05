"""
Caption, unit and source/note lines around tables and figures.

CAG reports print a caption ("Table 3.2: Details of grants", "Chart 1.1: …") above
or below a table or figure, a unit line ("(₹ in crore)") above a table, and source
or note lines below it. Phase 6 attaches these to their table or figure instead of
keeping them as tiny separate chunks.
"""

import re
from typing import Optional

CAPTION_RE = re.compile(
    r"^\s*(?P<kind>Table|Chart|Figure|Fig\.|Graph|Statement|Exhibit|Box|Map|Picture|"
    r"Photograph|Photo|Diagram|Image)\s*(?:No\.?)?\s*[-–:.]?\s*"
    r"(?P<number>(?:\d+|[IVX]+)(?:\s*[.\-–]\s*\d+)*(?:\s*\([a-z]\))?)(?![\d])",
    re.IGNORECASE,
)

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

TABLE_KINDS = {"table", "statement"}
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
    return {
        "kind": m.group("kind").lower(),
        "number": number,
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
