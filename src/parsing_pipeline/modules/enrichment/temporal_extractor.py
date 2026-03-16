"""
Temporal Extractor: Extracts audit periods, reference years, and
temporal context from CAG report text.
"""

import re
from typing import List, Dict, Optional, Tuple, Any


class TemporalExtractor:

    # Audit period patterns (document-level, usually in introduction/scope)
    # Note: [-–—] matches regular hyphen, en dash, and em dash
    AUDIT_PERIOD_PATTERNS = [
        # "covering the period 2019-20 to 2022-23" or "covers the period"
        r"(?:covering|covers|for)\s+(?:the\s+)?period\s+(\d{4})[-–—](\d{2,4})\s+to\s+(\d{4})[-–—](\d{2,4})",
        # "during 2019-20 to 2022-23"
        r"during\s+(\d{4})[-–—](\d{2,4})\s+to\s+(\d{4})[-–—](\d{2,4})",
        # "from 2019-20 to 2022-23"
        r"from\s+(\d{4})[-–—](\d{2,4})\s+to\s+(\d{4})[-–—](\d{2,4})",
        # "for the years 2019-20 to 2022-23"
        r"(?:for|during)\s+(?:the\s+)?years?\s+(\d{4})[-–—](\d{2,4})\s+to\s+(\d{4})[-–—](\d{2,4})",
        # "period from April 2019 to March 2023"
        r"period\s+from\s+\w+\s+(\d{4})\s+to\s+\w+\s+(\d{4})",
        # Simple pattern without keywords: "2019-20 to 2022-23" (fallback)
        r"\b(\d{4})[-–—](\d{2,4})\s+to\s+(\d{4})[-–—](\d{2,4})",
    ]

    # Individual year-range patterns (chunk-level)
    # Matches regular hyphen, en dash, and em dash
    YEAR_RANGE_PATTERN = re.compile(
        r"(\d{4})[-–—](\d{2,4})", re.IGNORECASE
    )

    # Standalone year
    YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

    # Previous audit references
    PREVIOUS_AUDIT_PATTERNS = [
        r"(?:outstanding|pending)\s+(?:paras?|observations?|audit\s+observations?)\s+"
        r"(?:from|of|since)\s+(?:the\s+)?(?:year\s+)?(\d{4})",
        r"(?:earlier|previous|prior)\s+(?:audit|report)\s+(?:of|for|in)\s+(\d{4})",
        r"(?:Report\s+No\.?\s*\d+\s+of\s+)(\d{4})",
        r"(?:ATN|Action\s+Taken\s+Note).*?(\d{4})",
    ]

    def __init__(self):
        self._audit_period_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.AUDIT_PERIOD_PATTERNS
        ]
        self._prev_audit_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.PREVIOUS_AUDIT_PATTERNS
        ]

    def _normalize_fy_year(self, base: str, suffix: str) -> int:
        """Convert '2019' + '20' → 2019, or '2019' + '2020' → 2019."""
        return int(base)

    def extract_audit_period(self, full_text: str) -> Optional[Dict[str, int]]:
        """
        Extract the document-level audit period from intro/scope text.

        Returns: {"start_year": 2019, "end_year": 2023} or None
        """
        for pattern in self._audit_period_patterns:
            match = pattern.search(full_text)
            if match:
                groups = match.groups()
                if len(groups) >= 4:
                    start_year = int(groups[0])
                    end_year = int(groups[2])
                    if 2000 <= start_year <= 2030 and 2000 <= end_year <= 2030:
                        return {"start_year": start_year, "end_year": end_year}
                elif len(groups) == 2:
                    start_year = int(groups[0])
                    end_year = int(groups[1])
                    if 2000 <= start_year <= 2030 and 2000 <= end_year <= 2030:
                        return {"start_year": start_year, "end_year": end_year}
        return None

    def extract_reference_years(self, text: str) -> List[int]:
        """Extract all years mentioned in a text block."""
        years = set()

        # Year ranges: "2019-20" → 2019
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

        return sorted(years)

    def extract_previous_audit_refs(self, text: str) -> List[Dict[str, Any]]:
        """Extract references to previous audits/reports."""
        refs = []
        for pattern in self._prev_audit_patterns:
            for match in pattern.finditer(text):
                year = int(match.group(1))
                if 2000 <= year <= 2030:
                    refs.append({
                        "year": year,
                        "raw_text": match.group(0).strip()[:100],
                    })
        return refs

    def extract_temporal_metadata(
        self,
        child_chunks: List[Dict],
        section_classifications: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Extract document-level temporal coverage.

        Scans introduction/scope sections first for audit period,
        then aggregates all years across all chunks.

        Returns: {
            "audit_period": {"start_year": 2019, "end_year": 2023} or None,
            "reference_years": [2018, 2019, 2020, ...],
            "previous_audit_refs": [{"year": 2018, "raw_text": "..."}],
        }
        """
        # Priority: scan intro/scope sections for audit period
        intro_text = ""
        if section_classifications:
            intro_section_types = {"introduction", "audit_scope", "audit_objectives", "executive_summary"}
            intro_chunk_ids = {
                sc.get("chunk_id") or sc.get("section_title", "")
                for sc in section_classifications
                if sc.get("section_type") in intro_section_types
            }
            # Gather text from chunks whose parent matches intro sections
            for chunk in child_chunks:
                pid = chunk.get("parent_chunk_id", "")
                if pid in intro_chunk_ids:
                    intro_text += " " + chunk.get("content", "")
        else:
            # Fallback: use first 20 chunks
            for chunk in child_chunks[:20]:
                intro_text += " " + chunk.get("content", "")

        audit_period = self.extract_audit_period(intro_text)

        # If not found in intro, scan all chunks
        if not audit_period:
            full_text = " ".join(c.get("content", "") for c in child_chunks[:50])
            audit_period = self.extract_audit_period(full_text)

        # Aggregate all reference years
        all_years = set()
        all_prev_refs = []
        for chunk in child_chunks:
            content = chunk.get("content", "")
            all_years.update(self.extract_reference_years(content))
            all_prev_refs.extend(self.extract_previous_audit_refs(content))

        # Deduplicate previous refs by year
        seen_years = set()
        unique_refs = []
        for ref in all_prev_refs:
            if ref["year"] not in seen_years:
                seen_years.add(ref["year"])
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
                refs.append({
                    "type": "year_range",
                    "start_year": base,
                    "end_year": end,
                    "raw_text": match.group(0),
                })

        return refs
