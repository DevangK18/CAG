"""
Number grounding check for generated summaries (D-10a-07).

Every number a summary states should come from the report. This extracts the
numbers from a summary and checks each one against the report's own text. A
number is grounded if the report states it, or if it is a rounding or
truncation of a number the report states (6,259.25 -> 6,259.3, 6,259 or 6259).
Indian digit grouping (1,23,456) and Western grouping (123,456) both compare
equal to the ungrouped number.

Counts below 10 without a decimal point are ignored: they are list markers,
section numbers and small counts that would only add noise.

Pure functions only; nothing here calls a model or touches the disk except
``build_source_text`` when given a PDF path.
"""

import json
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional, Union

DEFAULT_THRESHOLD_PCT = 10.0

# A digit run, optionally grouped with commas (Indian 1,23,456 or Western 123,456)
# and with a decimal part. Not part of a word or of another number's decimals,
# and not a page cite ("p.91", "pp.12"), but "Rs.500" still counts.
_NUM = re.compile(
    r"(?<![\w])(?<!\d\.)(?<!p\.)(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w])"
)

_MAX_EXAMPLES = 10

# Metadata values that a summary may legitimately quote (report number, year)
# but that the chunk text does not always repeat.
_METADATA_KEYS = ("report_title", "report_no", "report_year", "publication_date")


def numbers(text: str) -> list[str]:
    """Numbers in ``text`` as plain digit strings (commas removed), in order."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(1).replace(",", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        if value < 10 and "." not in raw:
            continue
        out.append(raw)
    return out


def _norm(raw: str) -> str:
    """Canonical form: no trailing decimal zeros, no leading zeros."""
    return format(Decimal(raw).normalize(), "f")


def _variants(raw: str) -> set[str]:
    """``raw`` plus every rounding and truncation to 0, 1 or 2 decimals."""
    value = Decimal(raw)
    out = {_norm(raw)}
    for places in ("1", "0.1", "0.01"):
        q = Decimal(places)
        for mode in (ROUND_HALF_UP, ROUND_DOWN):
            out.add(_norm(str(value.quantize(q, rounding=mode))))
    return out


def source_numbers(source_text: str) -> set[str]:
    """Every number form a grounded summary may use, given the report text."""
    found = set()
    for raw in numbers(source_text):
        found |= _variants(raw)
    return found


def build_source_text(
    chunks_json: dict, pdf_path: Optional[Union[str, Path]] = None
) -> str:
    """
    The report's own text, from a ``*_chunks.json`` dict.

    Child chunk content, parent TOC entries, structured table and chart data and
    the report metadata. The PDF text is added when ``pdf_path`` exists, since
    chunks can miss text (dropped blocks, tables kept only as images).
    """
    parts = [
        str((chunks_json.get("report_metadata") or {}).get(k) or "")
        for k in _METADATA_KEYS
    ]
    for chunk in chunks_json.get("child_chunks") or []:
        parts.append(chunk.get("content") or "")
        if chunk.get("structured_data"):
            parts.append(json.dumps(chunk["structured_data"], ensure_ascii=False))
    for parent in chunks_json.get("parent_chunks") or []:
        parts.append(parent.get("toc_entry") or "")

    if pdf_path and Path(pdf_path).exists():
        import fitz

        with fitz.open(pdf_path) as doc:
            parts.extend(page.get_text() for page in doc)

    return "\n".join(p for p in parts if p)


def check_grounding(
    summary_text: str,
    source: Union[str, Iterable[str]],
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> dict:
    """
    Check the numbers in ``summary_text`` against the report.

    Args:
        summary_text: Generated summary.
        source: The report text, or a set from ``source_numbers`` (compute it
            once per report when checking several variants).
        threshold_pct: Highest share of ungrounded numbers that still passes.

    Returns:
        {numbers, ungrounded, ungrounded_pct, examples, grounded}. ``examples``
        lists up to 10 ungrounded numbers as they appear in the summary.
    """
    known = source_numbers(source) if isinstance(source, str) else set(source)
    nums = numbers(summary_text)
    missing = [n for n in nums if _norm(n) not in known]
    pct = round(100 * len(missing) / len(nums), 1) if nums else 0.0
    return {
        "numbers": len(nums),
        "ungrounded": len(missing),
        "ungrounded_pct": pct,
        "examples": missing[:_MAX_EXAMPLES],
        "grounded": pct <= threshold_pct,
    }
