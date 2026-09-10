"""
R4: Unit tests for executive summary section flagging in FindingExtractor.

Tests the _is_executive_summary_section method that flags findings from
executive summary/overview sections to avoid double-counting.

Detection criteria:
1. Page is below tier-specific threshold (union: 25, state: 20, local: 15)
2. Chapter OR section contains executive summary keywords
"""

import pytest
from src.parsing_pipeline.modules.enrichment.finding_extractor import FindingExtractor


@pytest.fixture
def extractor():
    """Create FindingExtractor instance."""
    return FindingExtractor()


class TestExecSummaryPageThresholds:
    """Test page-based detection with tier-specific thresholds."""

    def test_union_below_threshold(self, extractor):
        """Union report page 20 with overview keyword should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=20,
            chapter="Overview",
            section="Key Findings",
            government_body_type="union",
        )
        assert is_exec is True

    def test_union_at_threshold_not_flagged(self, extractor):
        """Union report page 25 (at threshold) should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=25,
            chapter="Overview",
            section="Key Findings",
            government_body_type="union",
        )
        assert is_exec is False

    def test_union_above_threshold_not_flagged(self, extractor):
        """Union report page 30 should NOT flag regardless of keywords."""
        is_exec = extractor._is_executive_summary_section(
            page=30,
            chapter="Executive Summary",
            section="Highlights",
            government_body_type="union",
        )
        assert is_exec is False

    def test_state_below_threshold(self, extractor):
        """State report page 15 with overview keyword should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=15,
            chapter="OVERVIEW",
            section=None,
            government_body_type="state",
        )
        assert is_exec is True

    def test_state_at_threshold_not_flagged(self, extractor):
        """State report page 20 (at threshold) should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=20,
            chapter="Overview",
            section="Summary",
            government_body_type="state",
        )
        assert is_exec is False

    def test_local_body_below_threshold(self, extractor):
        """Local body report page 10 with overview keyword should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter="Preface",
            section="Overview",
            government_body_type="local_body",
        )
        assert is_exec is True

    def test_local_body_at_threshold_not_flagged(self, extractor):
        """Local body report page 15 (at threshold) should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=15,
            chapter="Overview",
            section=None,
            government_body_type="local_body",
        )
        assert is_exec is False


class TestExecSummaryKeywordDetection:
    """Test keyword-based detection of executive summary sections."""

    def test_overview_keyword_in_chapter(self, extractor):
        """'overview' in chapter should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter="CHAPTER – I AN OVERVIEW OF THE FUNCTIONING",
            section=None,
            government_body_type="state",
        )
        assert is_exec is True

    def test_executive_summary_keyword(self, extractor):
        """'executive summary' in chapter should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=5,
            chapter="Executive Summary",
            section=None,
            government_body_type="union",
        )
        assert is_exec is True

    def test_preface_keyword(self, extractor):
        """'preface' in chapter should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=8,
            chapter="Preface",
            section="Compliance Audit- Urban Local Bodies",
            government_body_type="local_body",
        )
        assert is_exec is True

    def test_highlights_keyword(self, extractor):
        """'highlights' in section should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=12,
            chapter="Chapter I",
            section="Highlights of Audit Findings",
            government_body_type="state",
        )
        assert is_exec is True

    def test_key_findings_keyword(self, extractor):
        """'key findings' in section should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter="Introduction",
            section="Key Findings",
            government_body_type="union",
        )
        assert is_exec is True

    def test_at_a_glance_keyword(self, extractor):
        """'at a glance' in section should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=3,
            chapter="Report",
            section="At A Glance",
            government_body_type="local_body",
        )
        assert is_exec is True

    def test_brief_snapshot_keyword(self, extractor):
        """'brief snapshot' in section should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=11,
            chapter="Performance Audit",
            section="Brief Snapshot of Findings",
            government_body_type="state",
        )
        assert is_exec is True

    def test_case_insensitive_keyword_match(self, extractor):
        """Keywords should match case-insensitively."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter="EXECUTIVE SUMMARY",
            section="HIGHLIGHTS",
            government_body_type="union",
        )
        assert is_exec is True


class TestNonExecSummarySections:
    """Test that non-executive summary sections are NOT flagged."""

    def test_chapter_without_keywords(self, extractor):
        """Regular chapter on early page without keywords should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter="CHAPTER – II COMPLIANCE AUDIT",
            section="Audit of Revenue Receipts",
            government_body_type="state",
        )
        assert is_exec is False

    def test_detailed_findings_chapter(self, extractor):
        """Detailed findings chapter on page 50 should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=50,
            chapter="CHAPTER – IV COMPLIANCE AUDIT",
            section="Avoidable Expenditure",
            government_body_type="local_body",
        )
        assert is_exec is False

    def test_performance_audit_chapter(self, extractor):
        """Performance audit chapter without overview keyword should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=80,
            chapter="CHAPTER -V PERFORMANCE AUDIT",
            section="Solid Waste Management",
            government_body_type="local_body",
        )
        assert is_exec is False

    def test_early_page_no_keywords(self, extractor):
        """Early page but no keywords should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=5,
            chapter="Table of Contents",
            section=None,
            government_body_type="union",
        )
        assert is_exec is False


class TestEdgeCases:
    """Test edge cases for executive summary detection."""

    def test_none_chapter_and_section(self, extractor):
        """None chapter and section should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter=None,
            section=None,
            government_body_type="state",
        )
        assert is_exec is False

    def test_empty_strings(self, extractor):
        """Empty chapter and section should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=5,
            chapter="",
            section="",
            government_body_type="local_body",
        )
        assert is_exec is False

    def test_page_zero(self, extractor):
        """Page 0 (cover page) with overview should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=0,
            chapter="Overview",
            section=None,
            government_body_type="union",
        )
        assert is_exec is True

    def test_keyword_in_section_only(self, extractor):
        """Keyword only in section (not chapter) should still flag."""
        is_exec = extractor._is_executive_summary_section(
            page=10,
            chapter="Chapter I",
            section="Overview of Audit Results",
            government_body_type="state",
        )
        assert is_exec is True

    def test_unknown_tier_uses_default(self, extractor):
        """Unknown tier should use default threshold (20)."""
        is_exec = extractor._is_executive_summary_section(
            page=15,
            chapter="Overview",
            section=None,
            government_body_type="unknown_tier",
        )
        assert is_exec is True  # 15 < 20 (default) and has keyword


class TestBRReportCases:
    """Test specific cases from BR_2024_03 report."""

    def test_br_overview_chapter(self, extractor):
        """BR report OVERVIEW section on page 11 should flag."""
        is_exec = extractor._is_executive_summary_section(
            page=11,
            chapter="Preface",
            section="OVERVIEW",
            government_body_type="local_body",
        )
        assert is_exec is True

    def test_br_compliance_audit_ulb_page_11(self, extractor):
        """BR report Compliance Audit- Urban Local Bodies section on page 11 should flag if under Preface."""
        is_exec = extractor._is_executive_summary_section(
            page=11,
            chapter="Preface",
            section="Compliance Audit- Urban Local Bodies",
            government_body_type="local_body",
        )
        # Has 'preface' keyword, page 11 < 15, should flag
        assert is_exec is True

    def test_br_performance_audit_page_12(self, extractor):
        """BR report Performance Audit recommendation section on page 12."""
        is_exec = extractor._is_executive_summary_section(
            page=12,
            chapter="Performance Audit on \"Solid Waste Management in the Urban Local Bodies of Bihar\"",
            section="Recommendation",
            government_body_type="local_body",
        )
        # No overview/exec summary keywords, but page 12 < 15
        # "recommendation" is not an exec summary keyword, so should NOT flag
        assert is_exec is False

    def test_br_detailed_chapter_page_63(self, extractor):
        """BR report detailed compliance audit chapter on page 63 should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=63,
            chapter="CHAPTER –IV COMPLIANCE AUDIT",
            section="Avoidable Expenditure",
            government_body_type="local_body",
        )
        assert is_exec is False

    def test_br_performance_audit_page_140(self, extractor):
        """BR report performance audit chapter on page 140 should NOT flag."""
        is_exec = extractor._is_executive_summary_section(
            page=140,
            chapter="CHAPTER -V PERFORMANCE AUDIT",
            section="Procurement of Dustbins",
            government_body_type="local_body",
        )
        assert is_exec is False
