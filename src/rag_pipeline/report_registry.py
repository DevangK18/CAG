"""
Report Registry - Central source of truth for report metadata and time series.

This module provides:
1. ReportInfo - Complete metadata for each report
2. TimeSeries - Groups of related reports across years
3. ReportRegistry - Singleton registry that loads from JSON chunk files

Usage:
    from report_registry import get_registry

    registry = get_registry()
    registry.load_from_json_dir(Path("data/processed"))

    # Get report info
    info = registry.get_report("2025_16_CAG_Report...")
    print(info.report_title, info.audit_year)

    # Get time series
    series = registry.get_series("frbm_compliance")
    for report in registry.get_reports_in_series("frbm_compliance"):
        print(f"{report.audit_year}: {report.report_title}")
"""

import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ReportInfo:
    """Complete information about a report."""

    report_id: str
    report_title: str
    report_no: str
    filename: str
    report_year: int  # Publication year (e.g., 2025)
    audit_year: str  # Audit period (e.g., "2023-24")
    ministry: str
    sector: str
    report_type: str
    series_id: Optional[str] = None  # Which time series this belongs to

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "report_id": self.report_id,
            "report_title": self.report_title,
            "report_no": self.report_no,
            "filename": self.filename,
            "report_year": self.report_year,
            "audit_year": self.audit_year,
            "ministry": self.ministry,
            "sector": self.sector,
            "report_type": self.report_type,
            "series_id": self.series_id,
        }


@dataclass
class TimeSeries:
    """A time series of related reports across multiple years."""

    series_id: str
    name: str
    description: str
    report_ids: List[str] = field(default_factory=list)  # Ordered by audit year

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "series_id": self.series_id,
            "name": self.name,
            "description": self.description,
            "report_ids": self.report_ids,
        }


class ReportRegistry:
    """
    Central registry for report metadata and time series.

    Loads metadata from JSON chunk files and organizes reports into
    time series for year-over-year analysis.
    """

    # Time series definitions - these define which reports belong together
    SERIES_DEFINITIONS = {
        "union_govt_accounts": {
            "name": "Union Government Accounts (Financial Audit)",
            "description": "Annual financial audit of Union Government accounts examining receipts, expenditure, and fiscal compliance",
            "pattern": r"Union.?Government.?Accounts.*Financial.?Audit|Accounts.?of.?the.?Union.?Government",
        },
        "frbm_compliance": {
            "name": "FRBM Act Compliance Audit",
            "description": "Compliance audit of Fiscal Responsibility and Budget Management Act, 2003",
            "pattern": r"Fiscal.?Responsibility.*Budget.?Management|FRBM",
        },
        "direct_taxes_audit": {
            "name": "Direct Taxes Compliance Audit",
            "description": "Compliance audit on Direct Taxes for the Union Government, Department of Revenue",
            # Match Compliance Audit on Direct Taxes, OR short titles with just "Department of Revenue – Direct Taxes"
            # Exclude Performance Audits (like Co-operative Societies audit)
            "pattern": r"(?:Compliance.?Audit.*Direct.?[Tt]axes|Direct.?[Tt]axes.*Compliance|^Report\s+No\.?\s*\d+\s+of\s+\d{4}\s*[-–]\s*Union\s+Government.*Direct.?Taxes)",
            "exclude_pattern": r"Performance.?Audit",  # Exclude performance audits
        },
    }

    def __init__(self):
        self._reports: Dict[str, ReportInfo] = {}
        self._series: Dict[str, TimeSeries] = {}
        self._loaded = False

    def load_from_json_dir(self, processed_dir: Path) -> int:
        """
        Load report metadata from JSON chunk files.

        Args:
            processed_dir: Directory containing *_chunks.json files

        Returns:
            Number of reports loaded
        """
        processed_dir = Path(processed_dir)

        if not processed_dir.exists():
            logger.warning(f"Processed directory not found: {processed_dir}")
            return 0

        count = 0

        # Find all chunk JSON files
        json_files = list(processed_dir.glob("*_chunks.json"))
        if not json_files:
            json_files = list(processed_dir.glob("*_enriched.json"))

        logger.info(f"Loading metadata from {len(json_files)} JSON files")

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                meta = data.get("report_metadata", {})
                if not meta:
                    # Try to get from first child chunk
                    children = data.get("child_chunks", [])
                    if children:
                        meta = children[0].get("metadata", {}).get("source", {})

                if not meta:
                    logger.warning(f"No metadata in {json_file.name}")
                    continue

                report_id = meta.get(
                    "report_id",
                    json_file.stem.replace("_chunks", "").replace("_enriched", ""),
                )
                report_title = meta.get("report_title", "")
                filename = meta.get("source_filename", f"{report_id}.pdf")

                # Extract audit year from title first, then try filename
                audit_year = self._extract_audit_year(report_title)
                if not audit_year:
                    audit_year = self._extract_audit_year_from_filename(
                        filename
                    ) or self._extract_audit_year_from_filename(report_id)

                # Determine series membership
                series_id = self._match_series(report_title)

                self._reports[report_id] = ReportInfo(
                    report_id=report_id,
                    report_title=report_title,
                    report_no=meta.get("report_no", ""),
                    filename=filename,
                    report_year=meta.get("report_year", 0),
                    audit_year=audit_year,
                    ministry=meta.get("ministry", ""),
                    sector=meta.get("sector", ""),
                    report_type=meta.get("report_type", ""),
                    series_id=series_id,
                )
                count += 1

                if series_id:
                    logger.debug(
                        f"Loaded {report_id} -> series: {series_id}, audit_year: {audit_year}"
                    )

            except Exception as e:
                logger.error(f"Error loading {json_file.name}: {e}")

        # Build series from loaded reports
        self._build_series()
        self._loaded = True

        logger.info(f"Loaded {count} reports into registry")
        logger.info(f"Built {len(self._series)} time series")

        return count

    def _extract_audit_year(self, title: str) -> str:
        """
        Extract audit year like '2023-24' from report title.

        Handles formats:
        - "for the year 2023-24"
        - "2022-23 Union Government"
        - "period 2020-21"
        - "year ended March 2022" -> "2021-22"
        - "for period ended March 2023" -> "2022-23"
        """
        # Try standard year range format (2023-24, 2022-23)
        match = re.search(r"(\d{4})-(\d{2,4})", title)
        if match:
            year1 = match.group(1)
            year2 = match.group(2)
            if len(year2) == 2:
                return f"{year1}-{year2}"
            else:
                return f"{year1}-{year2[-2:]}"

        # Try "year ended March YYYY" or "period ended March YYYY" format
        match = re.search(
            r"(?:year|period)\s+ended\s+March\s+(\d{4})", title, re.IGNORECASE
        )
        if match:
            end_year = int(match.group(1))
            start_year = end_year - 1
            return f"{start_year}-{str(end_year)[-2:]}"

        # Try single year format "year YYYY"
        match = re.search(r"year\s+(\d{4})", title.lower())
        if match:
            return match.group(1)

        # Try period format without range "period YYYY"
        match = re.search(r"period\s+(\d{4})", title.lower())
        if match:
            return match.group(1)

        return ""

    def _extract_audit_year_from_filename(self, filename: str) -> str:
        """
        Extract audit year from filename patterns like '202021', '202122', '202223'.

        These appear in filenames like:
        - 2022_29_Compliance_Audit_on_Direct_taxes_for_period_202021_...
        - 2024_13_Compliance_Audit_on_Direct_taxes_for_period_202122_...
        """
        # Match 6-digit year pattern: 202021 -> 2020-21
        match = re.search(r"(\d{4})(\d{2})(?:_|\.pdf|$)", filename)
        if match:
            year1 = match.group(1)
            year2 = match.group(2)
            # Validate it looks like a fiscal year (e.g., 2020+21, 2021+22)
            if int(year2) == int(year1[-2:]) + 1 or (
                year2 == "00" and year1.endswith("99")
            ):
                return f"{year1}-{year2}"

        return ""

    def _match_series(self, title: str) -> Optional[str]:
        """Determine which time series a report belongs to based on title."""
        for series_id, config in self.SERIES_DEFINITIONS.items():
            # Check exclude pattern first
            exclude_pattern = config.get("exclude_pattern")
            if exclude_pattern and re.search(exclude_pattern, title, re.IGNORECASE):
                continue

            # Check include pattern
            if re.search(config["pattern"], title, re.IGNORECASE):
                return series_id
        return None

    def _build_series(self):
        """Build TimeSeries objects from loaded reports."""
        self._series = {}

        for series_id, config in self.SERIES_DEFINITIONS.items():
            # Find all reports belonging to this series
            report_ids = [
                r.report_id for r in self._reports.values() if r.series_id == series_id
            ]

            if not report_ids:
                continue

            # Sort by audit year (oldest first for chronological order)
            report_ids.sort(key=lambda rid: self._reports[rid].audit_year or "9999")

            self._series[series_id] = TimeSeries(
                series_id=series_id,
                name=config["name"],
                description=config["description"],
                report_ids=report_ids,
            )

            years = [self._reports[rid].audit_year for rid in report_ids]
            logger.info(
                f"Series '{series_id}': {len(report_ids)} reports, years: {years}"
            )

    def get_report(self, report_id: str) -> Optional[ReportInfo]:
        """Get report metadata by ID."""
        return self._reports.get(report_id)

    def get_all_reports(self) -> List[ReportInfo]:
        """Get all loaded reports."""
        return list(self._reports.values())

    def get_series(self, series_id: str) -> Optional[TimeSeries]:
        """Get time series by ID."""
        return self._series.get(series_id)

    def get_all_series(self) -> List[TimeSeries]:
        """Get all time series."""
        return list(self._series.values())

    def get_reports_in_series(self, series_id: str) -> List[ReportInfo]:
        """Get all reports in a time series, ordered by audit year."""
        series = self._series.get(series_id)
        if not series:
            return []
        return [self._reports[rid] for rid in series.report_ids if rid in self._reports]

    def get_series_years(self, series_id: str) -> List[str]:
        """Get list of audit years covered by a series."""
        reports = self.get_reports_in_series(series_id)
        return [r.audit_year for r in reports if r.audit_year]

    def find_report_by_pattern(self, pattern: str) -> List[ReportInfo]:
        """Find reports matching a regex pattern in title or ID."""
        matches = []
        regex = re.compile(pattern, re.IGNORECASE)
        for report in self._reports.values():
            if regex.search(report.report_id) or regex.search(report.report_title):
                matches.append(report)
        return matches

    def is_loaded(self) -> bool:
        """Check if registry has been loaded."""
        return self._loaded

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_reports": len(self._reports),
            "total_series": len(self._series),
            "series": {
                sid: {
                    "name": s.name,
                    "report_count": len(s.report_ids),
                    "years": self.get_series_years(sid),
                }
                for sid, s in self._series.items()
            },
            "reports_without_series": len(
                [r for r in self._reports.values() if not r.series_id]
            ),
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_registry: Optional[ReportRegistry] = None


def get_registry() -> ReportRegistry:
    """
    Get or create the report registry singleton.

    The registry is lazily initialized - call load_from_json_dir()
    to populate it with data.
    """
    global _registry
    if _registry is None:
        _registry = ReportRegistry()
    return _registry


def init_registry(processed_dir: Path) -> ReportRegistry:
    """
    Initialize the registry with data from a directory.

    Convenience function that gets the singleton and loads data.
    """
    registry = get_registry()
    if not registry.is_loaded():
        registry.load_from_json_dir(processed_dir)
    return registry
