"""
P2-21: Unit tests for temporal extraction guards.

Tests for:
1. Future year filtering based on report_year
2. Fiscal year end-year parsing fix (2021-22 → end_year=2022)
"""

import pytest
from src.parsing_pipeline.modules.enrichment.temporal_extractor import TemporalExtractor


@pytest.fixture
def extractor():
    """Create a TemporalExtractor instance."""
    return TemporalExtractor()


class TestFutureYearFilteringP221:
    """P2-21: Test future year filtering based on report_year."""

    def test_future_years_filtered_by_report_year(self, extractor):
        """P2-21: Years beyond report_year+1 should be filtered out."""
        text = "The audit covered 2020, 2021, and projections for 2025, 2026, 2027."

        result = extractor.extract_reference_years(text, report_year=2022)

        # 2020, 2021 should be kept, 2022, 2023 allowed (+1 lag)
        # 2025, 2026, 2027 should be filtered
        assert 2020 in result
        assert 2021 in result
        assert 2025 not in result
        assert 2026 not in result
        assert 2027 not in result

    def test_years_within_report_year_preserved(self, extractor):
        """P2-21: Years at or before report_year should be kept."""
        text = "Audit findings from 2018, 2019, 2020, and 2021."

        result = extractor.extract_reference_years(text, report_year=2022)

        assert result == [2018, 2019, 2020, 2021]

    def test_report_year_plus_one_allowed(self, extractor):
        """P2-21: report_year+1 should be allowed for publication lag."""
        text = "Report published in 2023 covering audit period."

        result = extractor.extract_reference_years(text, report_year=2022)

        # 2023 is report_year+1, should be allowed
        assert 2023 in result

    def test_no_report_year_no_filtering(self, extractor):
        """P2-21: Without report_year, all valid years should be kept."""
        text = "Years mentioned: 2020, 2025, 2030."

        result = extractor.extract_reference_years(text, report_year=None)

        # All years 2000-2030 should be kept
        assert 2020 in result
        assert 2025 in result
        assert 2030 in result

    def test_years_exactly_at_boundary(self, extractor):
        """P2-21: Years at exactly report_year+1 boundary."""
        text = "Data from 2021, 2022, and 2023."

        result = extractor.extract_reference_years(text, report_year=2022)

        assert 2021 in result
        assert 2022 in result
        assert 2023 in result  # report_year + 1

    def test_empty_text_returns_empty(self, extractor):
        """P2-21: Empty text should return empty list."""
        result = extractor.extract_reference_years("", report_year=2022)

        assert result == []


class TestFiscalYearEndYearP221:
    """P2-21: Test fiscal year end-year parsing."""

    def test_fy_end_year_correct_two_digit(self, extractor):
        """P2-21: '2021-22' should give end_year=2022."""
        result = extractor._normalize_fy_year_end("2021", "22")

        assert result == 2022

    def test_fy_end_year_correct_four_digit(self, extractor):
        """P2-21: '2021-2022' should give end_year=2022."""
        result = extractor._normalize_fy_year_end("2021", "2022")

        assert result == 2022

    def test_audit_period_fy_end_year(self, extractor):
        """P2-21: Audit period extraction should use correct end year."""
        text = "This audit covers the period 2019-20 to 2021-22."

        result = extractor.extract_audit_period(text)

        assert result is not None
        assert result["start_year"] == 2019
        assert result["end_year"] == 2022  # Not 2021!

    def test_fy_range_extraction(self, extractor):
        """P2-21: Multiple FY ranges should be extracted correctly."""
        text = "The audit covered 2019-20 to 2022-23 fiscal years."

        result = extractor.extract_audit_period(text)

        assert result is not None
        assert result["start_year"] == 2019
        assert result["end_year"] == 2023

    def test_fy_single_year(self, extractor):
        """P2-21: Standalone year should remain unchanged."""
        text = "The year 2022 was significant."

        result = extractor.extract_reference_years(text)

        assert 2022 in result


class TestTemporalMetadataP221:
    """P2-21: Test extract_temporal_metadata with report_year."""

    def test_temporal_metadata_filters_future_years(self, extractor):
        """P2-21: extract_temporal_metadata should filter future years."""
        child_chunks = [
            {"content": "Data from 2020 and 2021."},
            {"content": "Projections for 2025 and 2026."},
        ]

        result = extractor.extract_temporal_metadata(
            child_chunks, section_classifications=None, report_year=2022
        )

        # Should include 2020, 2021, but not 2025, 2026
        assert 2020 in result["reference_years"]
        assert 2021 in result["reference_years"]
        assert 2025 not in result["reference_years"]
        assert 2026 not in result["reference_years"]

    def test_temporal_metadata_without_report_year(self, extractor):
        """P2-21: Without report_year, no filtering should occur."""
        child_chunks = [
            {"content": "Data from 2020 and projections for 2028."},
        ]

        result = extractor.extract_temporal_metadata(
            child_chunks, section_classifications=None, report_year=None
        )

        assert 2020 in result["reference_years"]
        assert 2028 in result["reference_years"]
