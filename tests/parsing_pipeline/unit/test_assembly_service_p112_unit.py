"""
P1-12: Unit tests for Year Extraction Priority Fix.

Tests:
- Report No preferred over publication date
- Conflict detection and logging
- Fallback chain (Report No -> report_id -> publication_date)
"""

import pytest
from unittest.mock import MagicMock, patch

from src.parsing_pipeline.modules.assembly_service import AssemblyService
from src.core.data_contracts import DocumentTask


@pytest.fixture
def assembly_service(tmp_path):
    """Create AssemblyService with temp output directory."""
    output_dir = tmp_path / "processed"
    output_dir.mkdir()
    return AssemblyService(output_dir=str(output_dir))


@pytest.fixture
def mock_trace_emitter():
    """Create mock trace emitter."""
    emitter = MagicMock()
    emitter.emit_red_flag = MagicMock()
    return emitter


class TestYearExtractionPriority:
    """P1-12: Test that Report No is preferred over publication date."""

    def test_report_no_preferred_over_publication_date(self, assembly_service):
        """Report No '3 of 2024' + Date '2025-03-28' -> 2024"""
        task = DocumentTask(
            report_id="2024_03_Test_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "3 of 2024",
                "Date": "2025-03-28",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2024  # Report No year, not publication year

    def test_report_no_slash_format(self, assembly_service):
        """Report No '2024/15' + Date '2025-01-01' -> 2024"""
        task = DocumentTask(
            report_id="2024_15_Test_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "2024/15",
                "Date": "2025-01-01",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2024

    def test_report_no_underscore_format(self, assembly_service):
        """Report No '2024_10' + Date '2025-02-15' -> 2024"""
        task = DocumentTask(
            report_id="2024_10_Test_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "2024_10",
                "Date": "2025-02-15",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2024


class TestReportIdFallback:
    """P1-12: Test report_id fallback when Report No is missing."""

    def test_report_id_fallback_when_no_report_no(self, assembly_service):
        """report_id=GJ_2024_03_... + no Report No -> 2024"""
        task = DocumentTask(
            report_id="GJ_2024_03_Test_State_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Date": "2025-06-01",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2024  # From report_id

    def test_report_id_union_format(self, assembly_service):
        """report_id=2023_07_Performance_Audit + no Report No -> 2023"""
        task = DocumentTask(
            report_id="2023_07_Performance_Audit_Test",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Date": "2024-01-15",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2023

    def test_report_id_state_format(self, assembly_service):
        """report_id=OD_2025_05_School_Education -> 2025"""
        task = DocumentTask(
            report_id="OD_2025_05_School_Education",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={},
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2025


class TestPublicationDateFallback:
    """P1-12: Test publication_date fallback when both Report No and report_id unavailable."""

    def test_publication_date_fallback(self, assembly_service):
        """No Report No + malformed report_id -> use Date"""
        task = DocumentTask(
            report_id="untitled_report",  # No year in report_id
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Date": "2023-12-01",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2023

    def test_no_year_found_returns_none(self, assembly_service):
        """No sources available -> None"""
        task = DocumentTask(
            report_id="unknown_report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={},
        )
        year = assembly_service._extract_report_year(task)
        assert year is None


class TestConflictDetection:
    """P1-12: Test conflict detection when sources disagree."""

    def test_conflict_logged_and_flagged(self, assembly_service, mock_trace_emitter):
        """When sources disagree, red flag emitted."""
        assembly_service._trace_emitter = mock_trace_emitter

        task = DocumentTask(
            report_id="2024_03_GJ_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "3 of 2024",
                "Date": "2025-03-28",  # Different year!
            },
        )

        year = assembly_service._extract_report_year(task)

        # Should return Report No year (priority)
        assert year == 2024

        # Should emit red flag for conflict
        mock_trace_emitter.emit_red_flag.assert_called_once()
        call_args = mock_trace_emitter.emit_red_flag.call_args
        assert call_args[1]["phase"] == "8"
        assert call_args[1]["flag"] == "year_extraction_conflict"
        assert "sources" in call_args[1]["details"]
        assert call_args[1]["details"]["selected"] == 2024

    def test_no_conflict_when_years_match(self, assembly_service, mock_trace_emitter):
        """When sources agree, no red flag."""
        assembly_service._trace_emitter = mock_trace_emitter

        task = DocumentTask(
            report_id="2024_03_Test_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "3 of 2024",
                "Date": "2024-08-15",  # Same year
            },
        )

        year = assembly_service._extract_report_year(task)

        assert year == 2024
        mock_trace_emitter.emit_red_flag.assert_not_called()


class TestEdgeCases:
    """P1-12: Test edge cases in year extraction."""

    def test_invalid_year_in_report_no(self, assembly_service):
        """Report No with invalid format -> fallback to report_id"""
        task = DocumentTask(
            report_id="2023_05_Test_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "Not a year",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2023  # Fallback to report_id

    def test_report_no_unknown_value(self, assembly_service):
        """Report No = 'Unknown' -> fallback to report_id"""
        task = DocumentTask(
            report_id="2022_01_Test_Report",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Report No": "Unknown",
                "Date": "2023-01-01",
            },
        )
        year = assembly_service._extract_report_year(task)
        assert year == 2022  # Fallback to report_id

    def test_date_various_formats(self, assembly_service):
        """Test various date formats are parsed correctly."""
        # YYYY-MM-DD format
        task = DocumentTask(
            report_id="untitled",
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={"Date": "2021-06-15"},
        )
        assert assembly_service._extract_report_year(task) == 2021

    def test_year_validation_bounds(self, assembly_service):
        """Years outside 2000-2100 from report_id are rejected."""
        task = DocumentTask(
            report_id="1999_01_Old_Report",  # Before 2000
            source_url="http://example.com/report.pdf",
            local_pdf_path="/tmp/test.pdf",
            initial_metadata={
                "Date": "2020-01-01",
            },
        )
        year = assembly_service._extract_report_year(task)
        # 1999 is outside bounds, should fall back to Date
        assert year == 2020
