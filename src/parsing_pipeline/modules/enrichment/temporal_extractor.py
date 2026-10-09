"""
Temporal Extractor: Extracts audit periods, reference years, and
temporal context from CAG report text.
"""

import re
from typing import List, Dict, Optional, Tuple, Any


class TemporalExtractor:
    # Audit period patterns (document-level, usually in preface/scope/introduction),
    # strongest first. [-–—] matches regular hyphen, en dash, and em dash.
    _FY = r"(?:FYs?\s*)?(\d{4})[-–—](\d{2,4})"
    _LEAD = (
        r"(?:covering|covers|covered|cover|for|during|of|in)\s+(?:the\s+)?(?:audit\s+)?(?:financial\s+)?"
        r"(?:years?|period|FYs?)\s*(?:from\s+)?"
    )
    AUDIT_PERIOD_PATTERNS = [
        # "covering the period 2019-20 to 2022-23", "during FY 2018-19 to FY 2020-21",
        # "for the period 2017-18 and 2018-19"
        _LEAD + _FY + r"\s*(?:to|till|until|and|[-–—])\s*" + _FY,
        # "during 2019-20 to 2022-23", "from 2019-20 to 2022-23"
        r"(?:during|from|between)\s+" + _FY + r"\s*(?:to|till|until|and)\s*" + _FY,
        # "period from April 2019 to March 2023"
        r"period\s+(?:from\s+)?[A-Za-z]+,?\s+(\d{4})\s+(?:to|till)\s+[A-Za-z]+,?\s+(\d{4})",
        # One fiscal year or one span: "for the year 2022-23", "for the period 2017-2022",
        # "during the period 2015-22"
        _LEAD + _FY + r"(?![-–—]?\d)",
        # "during 2016-17", "during FY 2018-19"
        r"\bduring\s+" + _FY + r"(?![-–—]?\d)(?!\s*(?:to|and)\s+(?:FY\s*)?\d)",
        # Simple pattern without keywords: "2019-20 to 2022-23" (fallback)
        r"\b" + _FY + r"\s+to\s+" + _FY,
    ]
    # The first four name a period outright; the rest are tried only when no section has one
    _STRONG_PATTERNS = 4

    # Individual year-range patterns (chunk-level)
    # Matches regular hyphen, en dash, and em dash
    YEAR_RANGE_PATTERN = re.compile(r"(\d{4})[-–—](\d{2,4})", re.IGNORECASE)

    # Standalone year
    YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

    # Previous audit references. ATN is matched as a word and case-sensitively, so
    # Patna, Visakhapatnam and Ratnagiri are not Action Taken Notes; its year must
    # follow within the same sentence.
    PREVIOUS_AUDIT_PATTERNS = [
        r"(?i:(?:outstanding|pending)\s+(?:paras?|observations?|audit\s+observations?)\s+"
        r"(?:from|of|since)\s+(?:the\s+)?(?:year\s+)?)(\d{4})",
        r"(?i:(?:earlier|previous|prior|last)\s+(?:audit\s+)?(?:report|audit)s?\s*(?:of|for|in|\()\s*"
        r"(?:the\s+(?:year\s+)?)?)(\d{4})",
        r"(?i:Report\s+No\.?\s*)(\d{1,3})(?i:\s+of\s+)(\d{4})",
        r"\b(?:ATNs?|(?i:Action\s+Taken\s+Notes?))\b[^.]{0,60}?\b((?:19|20)\d{2})\b",
        r"\b(?:PAC|COPU|(?i:Public\s+Accounts\s+Committee|Committee\s+on\s+Public\s+Undertakings))\b"
        r"[^.]{0,60}?\b((?:19|20)\d{2})\b",
    ]

    # Where a report states its audit period, in the order to trust them
    PERIOD_SECTION_ORDER = [
        {"audit_scope", "audit_methodology"},
        {"preface", "acknowledgement"},
        {"introduction", "audit_objectives", "audit_criteria"},
        {"executive_summary"},
    ]

    def __init__(self):
        self._audit_period_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.AUDIT_PERIOD_PATTERNS
        ]
        self._prev_audit_patterns = [
            re.compile(p) for p in self.PREVIOUS_AUDIT_PATTERNS
        ]

    def _normalize_fy_year(self, base: str, suffix: str) -> int:
        """Convert '2019' + '20' → 2019 (start year), or '2019' + '2020' → 2019."""
        return int(base)

    def _normalize_fy_year_end(self, base: str, suffix: str) -> int:
        """
        P2-21: Convert fiscal year to END year.

        '2021' + '22' → 2022 (end year of fiscal 2021-22)
        '2021' + '2022' → 2022
        """
        base_int = int(base)
        if len(suffix) == 2:
            # "2021-22" → 2022
            century = str(base_int)[:2]
            return int(century + suffix)
        else:
            # "2021-2022" → 2022
            return int(suffix)

    def _period(self, groups: Tuple[str, ...]) -> Optional[Dict[str, int]]:
        """{"start_year", "end_year"} from a match, or None when it is not a plausible period."""
        if len(groups) == 4:
            # "2019-20 to 2022-23" -> 2019..2023
            start_year = int(groups[0])
            end_year = self._normalize_fy_year_end(groups[2], groups[3])
        else:
            # "2022-23" -> 2022..2023; "2015-22" -> 2015..2022; "April 2019 to March 2023",
            # "2017-2022" -> 2017..2022
            start_year = int(groups[0])
            end_year = self._normalize_fy_year_end(groups[0], groups[1])
        if 2000 <= start_year < end_year <= 2035 and end_year - start_year <= 15:
            return {"start_year": start_year, "end_year": end_year}
        return None

    def extract_audit_period(
        self,
        full_text: str,
        strong_only: bool = False,
        report_year: Optional[int] = None,
    ) -> Optional[Dict[str, int]]:
        """
        Extract the document-level audit period from preface/scope/intro text.

        Patterns are tried strongest first, and the first plausible match of the
        strongest pattern wins: start <= end, years 2000-2035, at most 15 years, and
        not ending after the report's year + 1.

        P2-21: Uses _normalize_fy_year_end() to get the correct end year
        for fiscal year patterns like "2021-22" → end_year=2022.

        Returns: {"start_year": 2019, "end_year": 2023} or None
        """
        patterns = self._audit_period_patterns
        if strong_only:
            patterns = patterns[: self._STRONG_PATTERNS]
        for pattern in patterns:
            for match in pattern.finditer(full_text or ""):
                period = self._period(match.groups())
                if period and (
                    report_year is None or period["end_year"] <= report_year + 1
                ):
                    return period
        return None

    def extract_reference_years(
        self, text: str, report_year: Optional[int] = None
    ) -> List[int]:
        """
        Extract all years mentioned in a text block.

        P2-21: Optionally filter years based on report_year.
        Future years beyond report_year+1 are filtered out to avoid
        including publication dates or projection years.

        Args:
            text: Text content to extract years from
            report_year: Optional report year to filter against (allows +1 for pub lag)

        Returns:
            Sorted list of years
        """
        years = set()

        # Year ranges: "2019-20" → 2019, 2020
        for match in self.YEAR_RANGE_PATTERN.finditer(text):
            base = int(match.group(1))
            if 2000 <= base <= 2030:
                years.add(base)
                # Also add the end year
                suffix = match.group(2)
                if len(suffix) == 2:
                    end = int(str(base)[:2] + suffix)
                else:
                    end = int(suffix)
                if 2000 <= end <= 2030:
                    years.add(end)

        # Standalone years
        for match in self.YEAR_PATTERN.finditer(text):
            year = int(match.group(1))
            if 2000 <= year <= 2030:
                years.add(year)

        # P2-21: Filter future years relative to report_year
        if report_year is not None:
            max_allowed_year = report_year + 1  # Allow +1 for publication lag
            years = {y for y in years if y <= max_allowed_year}

        return sorted(years)

    @staticmethod
    def own_report_number(report_no: Optional[str]) -> Optional[Tuple[int, int]]:
        """'08 of 2025' -> (8, 2025): the report's own number, which its cover and footers repeat."""
        m = re.search(r"(\d{1,3})\s*(?:of|/)\s*(\d{4})", report_no or "")
        return (int(m.group(1)), int(m.group(2))) if m else None

    def extract_previous_audit_refs(
        self, text: str, own_report: Optional[Tuple[int, int]] = None
    ) -> List[Dict[str, Any]]:
        """Extract references to previous audits/reports; the report's own number is not one."""
        refs = []
        for pattern in self._prev_audit_patterns:
            for match in pattern.finditer(text or ""):
                year = int(match.group(match.lastindex))
                if match.lastindex == 2 and own_report == (int(match.group(1)), year):
                    continue
                if 2000 <= year <= 2035:
                    refs.append(
                        {
                            "year": year,
                            "raw_text": match.group(0).strip()[:100],
                        }
                    )
        return refs

    def _single_years(
        self, text: str, report_year: Optional[int]
    ) -> Optional[Dict[str, int]]:
        """Every year one section names ("During the year 2017-18 ... During 2018-19"), as one span."""
        periods = [
            p
            for p in (
                self._period(m.groups())
                for m in self._audit_period_patterns[3].finditer(text or "")
            )
            if p and (report_year is None or p["end_year"] <= report_year + 1)
        ]
        if not periods:
            return None
        start = min(p["start_year"] for p in periods)
        end = max(p["end_year"] for p in periods)
        return (
            {"start_year": start, "end_year": end} if end - start <= 15 else periods[0]
        )

    def _period_from_sections(
        self,
        child_chunks: List[Dict],
        section_classifications: List[Dict],
        report_year: Optional[int],
    ) -> Optional[Dict[str, int]]:
        """
        Scope first, then preface, introduction and executive summary. In each, a
        stated range wins; otherwise the single years it names. Weak phrasing
        ("during 2016-17" anywhere) only when no section states a period.
        """
        types = {
            sc.get("chunk_id"): sc.get("section_type") for sc in section_classifications
        }
        texts = []
        for group in self.PERIOD_SECTION_ORDER:
            texts.append(
                " ".join(
                    c.get("content", "")
                    for c in child_chunks
                    if types.get(c.get("parent_chunk_id")) in group
                )
            )
        ranges = self._audit_period_patterns[:3]
        for text in texts:
            for pattern in ranges:
                for match in pattern.finditer(text):
                    period = self._period(match.groups())
                    if period and (
                        report_year is None or period["end_year"] <= report_year + 1
                    ):
                        return period
            period = self._single_years(text, report_year)
            if period:
                return period
        for text in texts:
            period = self.extract_audit_period(text, report_year=report_year)
            if period:
                return period
        return None

    def extract_temporal_metadata(
        self,
        child_chunks: List[Dict],
        section_classifications: Optional[List[Dict]] = None,
        report_year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Extract document-level temporal coverage.

        Scans scope, preface, introduction and executive-summary sections (in that
        order) for the audit period, then the start of the report; aggregates all
        years across all chunks.

        P2-21: Added report_year parameter to filter future years.

        Args:
            child_chunks: List of child chunk dicts
            section_classifications: Optional section classification list
            report_year: Optional report year for filtering future years

        Returns: {
            "audit_period": {"start_year": 2019, "end_year": 2023} or None,
            "reference_years": [2018, 2019, 2020, ...],
            "previous_audit_refs": [{"year": 2018, "raw_text": "..."}],
        }
        """
        audit_period = None
        if section_classifications:
            audit_period = self._period_from_sections(
                child_chunks, section_classifications, report_year
            )
        else:
            # Fallback: use first 20 chunks
            intro_text = " ".join(c.get("content", "") for c in child_chunks[:20])
            audit_period = self.extract_audit_period(
                intro_text, report_year=report_year
            )

        # If not found in intro, scan the start of the report
        if not audit_period:
            full_text = " ".join(c.get("content", "") for c in child_chunks[:50])
            audit_period = self.extract_audit_period(full_text, report_year=report_year)

        own_report = next(
            (
                self.own_report_number(c.get("report_no"))
                for c in child_chunks
                if c.get("report_no")
            ),
            None,
        )

        # Aggregate all reference years (P2-21: with report_year filtering)
        all_years = set()
        all_prev_refs = []
        for chunk in child_chunks:
            content = chunk.get("content", "")
            all_years.update(
                self.extract_reference_years(content, report_year=report_year)
            )
            all_prev_refs.extend(self.extract_previous_audit_refs(content, own_report))

        # Deduplicate previous refs by their text: one year can have several real references
        seen_texts = set()
        unique_refs = []
        for ref in all_prev_refs:
            key = " ".join(ref["raw_text"].lower().split())
            if key not in seen_texts:
                seen_texts.add(key)
                unique_refs.append(ref)

        return {
            "audit_period": audit_period,
            "reference_years": sorted(all_years),
            "previous_audit_refs": unique_refs,
        }

    def annotate_chunk_temporal(self, chunk: Dict) -> List[Dict[str, Any]]:
        """
        Extract temporal references for a single chunk.
        Returns list of {"type": "year_range"|"standalone_year", "start_year": X, "end_year": Y, "raw_text": ...}
        """
        content = chunk.get("content", "")
        refs = []

        for match in self.YEAR_RANGE_PATTERN.finditer(content):
            base = int(match.group(1))
            suffix = match.group(2)
            end = int(str(base)[:2] + suffix) if len(suffix) == 2 else int(suffix)
            if 2000 <= base <= 2030:
                refs.append(
                    {
                        "type": "year_range",
                        "start_year": base,
                        "end_year": end,
                        "raw_text": match.group(0),
                    }
                )

        return refs


def fill_audit_period_from_overview(
    temporal_coverage: Dict[str, Any], overview: Optional[Dict[str, Any]]
) -> bool:
    """
    Fill an empty audit_period from the Phase 10a overview's audit_scope.period
    ({"start": "2018-19", "end": "2022-23", "description": ...}). Phase 9 runs before
    the overview exists, so this is applied afterwards. Returns True when it filled one.
    """
    if not isinstance(temporal_coverage, dict) or temporal_coverage.get("audit_period"):
        return False
    scope = (overview or {}).get("audit_scope") or {}
    period = scope.get("period") if isinstance(scope, dict) else None
    if not isinstance(period, dict):
        return False
    extractor = TemporalExtractor()
    start = re.search(
        r"(\d{4})(?:\s*[-–—]\s*(\d{2,4}))?", str(period.get("start") or "")
    )
    end = re.search(r"(\d{4})(?:\s*[-–—]\s*(\d{2,4}))?", str(period.get("end") or ""))
    filled = None
    if start and end:
        start_year = int(start.group(1))
        # An end given as a fiscal year ends a year later: "2022-23" -> 2023
        end_year = (
            extractor._normalize_fy_year_end(end.group(1), end.group(2))
            if end.group(2)
            else int(end.group(1))
        )
        if 2000 <= start_year < end_year <= 2035 or (
            2000 <= start_year == end_year <= 2035 and not end.group(2)
        ):
            filled = {"start_year": start_year, "end_year": end_year}
    if filled is None and period.get("description"):
        filled = extractor.extract_audit_period(f"period {period['description']}")
    if filled is None:
        return False
    temporal_coverage["audit_period"] = filled
    temporal_coverage["audit_period_source"] = "overview"
    return True
