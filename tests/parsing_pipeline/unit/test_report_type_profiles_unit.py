"""
Unit tests for P1-1: Report Type Adaptation (report_type_profiles.py)

Tests report type detection, profile retrieval, and type-specific configurations.
"""

import pytest
from unittest.mock import Mock
from src.parsing_pipeline.modules import report_type_profiles
from src.core.data_contracts import DocumentTask


class TestReportTypeDetection:
    """Test report type detection from various signals."""

    def test_detect_from_explicit_metadata(self):
        """Test detection from explicit metadata field."""
        task = DocumentTask(
            task_id="test_1",
            manifest_file="test.xlsx",
            report_id="report_001",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Test Report"},
            status="pending",
            initial_metadata={"report_type": "compliance"},
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "compliance"

    def test_detect_from_title_compliance(self):
        """Test detection from title containing 'compliance'."""
        task = DocumentTask(
            task_id="test_2",
            manifest_file="test.xlsx",
            report_id="report_002",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Compliance Audit Report 2023"},
            status="pending",
            initial_metadata={"report_title": "Compliance Audit Report 2023"},
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "compliance"

    def test_detect_from_title_performance(self):
        """Test detection from title containing 'performance'."""
        task = DocumentTask(
            task_id="test_3",
            manifest_file="test.xlsx",
            report_id="report_003",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Performance Audit on PMGSY"},
            status="pending",
            initial_metadata={"report_title": "Performance Audit on PMGSY"},
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "performance"

    def test_detect_from_title_financial(self):
        """Test detection from title containing 'financial'."""
        task = DocumentTask(
            task_id="test_4",
            manifest_file="test.xlsx",
            report_id="report_004",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Financial Audit of Railways 2023"},
            status="pending",
            initial_metadata={"report_title": "Financial Audit of Railways 2023"},
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "financial"

    def test_detect_from_toc_structure_compliance(self):
        """Test detection from ToC with compliance keywords."""
        task = DocumentTask(
            task_id="test_5",
            manifest_file="test.xlsx",
            report_id="report_005",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Audit Report"},
            status="pending",
            initial_metadata={"report_title": "Audit Report"},
            scaffold={
                "toc": [
                    {"title": "Introduction", "page": 1},
                    {"title": "Audit Findings and Irregularities", "page": 10},
                    {"title": "Non-compliance with Rules", "page": 25},
                    {"title": "Audit Observations", "page": 40},
                ]
            },
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "compliance"

    def test_detect_from_toc_structure_performance(self):
        """Test detection from ToC with performance keywords."""
        task = DocumentTask(
            task_id="test_6",
            manifest_file="test.xlsx",
            report_id="report_006",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Audit Report"},
            status="pending",
            initial_metadata={"report_title": "Audit Report"},
            scaffold={
                "toc": [
                    {"title": "Introduction", "page": 1},
                    {"title": "Performance Assessment", "page": 10},
                    {"title": "Target Achievement", "page": 25},
                    {"title": "Efficiency and Effectiveness", "page": 40},
                ]
            },
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "performance"

    def test_detect_from_toc_structure_financial(self):
        """Test detection from ToC with financial keywords."""
        task = DocumentTask(
            task_id="test_7",
            manifest_file="test.xlsx",
            report_id="report_007",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Audit Report"},
            status="pending",
            initial_metadata={"report_title": "Audit Report"},
            scaffold={
                "toc": [
                    {"title": "Introduction", "page": 1},
                    {"title": "Financial Statements", "page": 10},
                    {"title": "Audit Opinion", "page": 25},
                    {"title": "Notes to Accounts", "page": 40},
                ]
            },
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "financial"

    def test_default_to_general(self):
        """Test fallback to 'general' when no clear signals."""
        task = DocumentTask(
            task_id="test_8",
            manifest_file="test.xlsx",
            report_id="report_008",
            source_url="http://example.com/test.pdf",
            local_pdf_path="/tmp/test.pdf",
            row_data={"report_title": "Report"},
            status="pending",
            initial_metadata={"report_title": "Report"},
        )
        detected = report_type_profiles.detect_report_type(task)
        assert detected == "general"


class TestReportTypeNormalization:
    """Test report type normalization."""

    def test_normalize_exact_match(self):
        """Test normalization of exact type names."""
        assert report_type_profiles.normalize_report_type("compliance") == "compliance"
        assert report_type_profiles.normalize_report_type("performance") == "performance"
        assert report_type_profiles.normalize_report_type("financial") == "financial"

    def test_normalize_compliance_variations(self):
        """Test normalization of compliance variations."""
        assert report_type_profiles.normalize_report_type("Compliance Audit") == "compliance"
        assert report_type_profiles.normalize_report_type("Regularity Audit") == "compliance"
        assert report_type_profiles.normalize_report_type("Propriety Audit") == "compliance"

    def test_normalize_performance_variations(self):
        """Test normalization of performance variations."""
        assert report_type_profiles.normalize_report_type("Performance Audit") == "performance"
        assert report_type_profiles.normalize_report_type("Efficiency Audit") == "performance"
        assert report_type_profiles.normalize_report_type("Effectiveness Review") == "performance"

    def test_normalize_financial_variations(self):
        """Test normalization of financial variations."""
        assert report_type_profiles.normalize_report_type("Financial Audit") == "financial"
        assert report_type_profiles.normalize_report_type("Accounts Audit") == "financial"
        assert report_type_profiles.normalize_report_type("Appropriation Audit") == "financial"

    def test_normalize_unknown_defaults_to_general(self):
        """Test that unknown types default to general."""
        assert report_type_profiles.normalize_report_type("Unknown Type") == "general"
        assert report_type_profiles.normalize_report_type("") == "general"


class TestProfileAccessors:
    """Test profile accessor functions."""

    def test_get_profile_compliance(self):
        """Test getting compliance profile."""
        profile = report_type_profiles.get_profile("compliance")
        assert "finding_patterns" in profile
        assert "section_markers" in profile
        assert profile["monetary_context"] == "irregular_expenditure"
        assert profile["evidence_weight"] == "high"

    def test_get_profile_performance(self):
        """Test getting performance profile."""
        profile = report_type_profiles.get_profile("performance")
        assert "finding_patterns" in profile
        assert profile["monetary_context"] == "performance_shortfall"
        assert profile["evidence_weight"] == "medium"

    def test_get_profile_financial(self):
        """Test getting financial profile."""
        profile = report_type_profiles.get_profile("financial")
        assert "finding_patterns" in profile
        assert profile["monetary_context"] == "financial_irregularity"
        assert profile["evidence_weight"] == "high"

    def test_get_finding_patterns(self):
        """Test getting finding patterns for a type."""
        patterns = report_type_profiles.get_finding_patterns("compliance")
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        # Check for specific compliance patterns
        assert any("non-?compliance" in p for p in patterns)

    def test_get_section_markers(self):
        """Test getting section markers for a type."""
        markers = report_type_profiles.get_section_markers("compliance")
        assert isinstance(markers, dict)
        assert "findings" in markers
        assert "recommendations" in markers

    def test_get_confidence_boost(self):
        """Test getting confidence boost multiplier."""
        # Compliance has higher boost (1.2)
        compliance_boost = report_type_profiles.get_confidence_boost("compliance")
        assert compliance_boost == 1.2

        # Performance has normal boost (1.0)
        performance_boost = report_type_profiles.get_confidence_boost("performance")
        assert performance_boost == 1.0

        # Financial has moderate boost (1.15)
        financial_boost = report_type_profiles.get_confidence_boost("financial")
        assert financial_boost == 1.15

    def test_get_evidence_weight(self):
        """Test getting evidence weight."""
        assert report_type_profiles.get_evidence_weight("compliance") == "high"
        assert report_type_profiles.get_evidence_weight("performance") == "medium"
        assert report_type_profiles.get_evidence_weight("financial") == "high"


class TestReportProfiles:
    """Test report profile configurations."""

    def test_all_profiles_have_required_fields(self):
        """Test that all profiles have required configuration fields."""
        required_fields = [
            "finding_patterns",
            "section_markers",
            "monetary_context",
            "evidence_weight",
            "confidence_boost",
            "description",
        ]

        for report_type, profile in report_type_profiles.REPORT_PROFILES.items():
            for field in required_fields:
                assert field in profile, f"Profile '{report_type}' missing field '{field}'"

    def test_finding_patterns_not_empty(self):
        """Test that all profiles have non-empty finding patterns."""
        for report_type, profile in report_type_profiles.REPORT_PROFILES.items():
            patterns = profile["finding_patterns"]
            assert isinstance(patterns, list)
            assert len(patterns) > 0, f"Profile '{report_type}' has empty finding patterns"

    def test_section_markers_structure(self):
        """Test that section markers have correct structure."""
        for report_type, profile in report_type_profiles.REPORT_PROFILES.items():
            markers = profile["section_markers"]
            assert isinstance(markers, dict)
            # Each marker type should have a list of keywords
            for marker_type, keywords in markers.items():
                assert isinstance(keywords, list)
                assert len(keywords) > 0

    def test_confidence_boost_range(self):
        """Test that confidence boost values are reasonable."""
        for report_type, profile in report_type_profiles.REPORT_PROFILES.items():
            boost = profile["confidence_boost"]
            assert isinstance(boost, (int, float))
            assert 0.5 <= boost <= 2.0, f"Unreasonable boost value for '{report_type}': {boost}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
