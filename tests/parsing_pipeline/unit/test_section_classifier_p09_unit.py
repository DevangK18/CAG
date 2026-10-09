"""
P0-09: Unit tests for SectionClassifier taxonomy expansion.

Tests:
- Expanded SectionType enum values
- Topic patterns (the secondary tag next to the section role)
- Classification accuracy for State/Local Body reports
"""

import pytest
from src.parsing_pipeline.modules.enrichment.section_classifier import (
    SectionClassifier,
    SectionType,
)


@pytest.fixture
def classifier():
    """Create SectionClassifier instance."""
    return SectionClassifier()


class TestExpandedSectionTypeEnum:
    """Test P0-09 expanded SectionType enum."""

    def test_new_section_types_exist(self):
        """Test that new section types are in the enum."""
        # Core new types from P0-09
        assert SectionType.FINANCIAL_MANAGEMENT.value == "financial_management"
        assert SectionType.EMPLOYMENT.value == "employment"
        assert SectionType.EXECUTION.value == "execution"
        assert SectionType.PLANNING.value == "planning"
        assert SectionType.CAPACITY_BUILDING.value == "capacity_building"
        assert SectionType.GRIEVANCE_REDRESSAL.value == "grievance_redressal"
        assert SectionType.IMPACT.value == "impact"
        assert SectionType.MONITORING_EVALUATION.value == "monitoring_evaluation"

    def test_additional_section_types_exist(self):
        """Test that additional section types are in the enum."""
        assert SectionType.COMPLIANCE_REVIEW.value == "compliance_review"
        assert SectionType.PERFORMANCE_AUDIT.value == "performance_audit"
        assert SectionType.INFRASTRUCTURE.value == "infrastructure"
        assert SectionType.SERVICE_DELIVERY.value == "service_delivery"
        assert SectionType.REGULATORY.value == "regulatory"
        assert SectionType.ENVIRONMENT.value == "environment"

    def test_original_types_preserved(self):
        """Test that original section types are preserved."""
        assert SectionType.EXECUTIVE_SUMMARY.value == "executive_summary"
        assert SectionType.FINDINGS.value == "findings"
        assert SectionType.RECOMMENDATIONS.value == "recommendations"
        assert SectionType.OTHER.value == "other"


class TestFinancialManagementPatterns:
    """Test P0-09 financial management section patterns."""

    def test_financial_management_title(self, classifier):
        """Test 'Financial Management' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Financial Management",
                "hierarchy": {},
            }
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "financial_management"
        )

    def test_fund_utilization_title(self, classifier):
        """Test 'Fund Utilization' title classification."""
        chunks = [
            {"chunk_id": "chunk_002", "toc_entry": "Fund Utilization", "hierarchy": {}}
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "financial_management"
        )

    def test_budgetary_control_title(self, classifier):
        """Test 'Budgetary Control' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_003",
                "toc_entry": "Budgetary Control and Management",
                "hierarchy": {},
            }
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "financial_management"
        )


class TestEmploymentPatterns:
    """Test P0-09 employment section patterns."""

    def test_employment_generation_title(self, classifier):
        """Test 'Employment Generation' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Employment Generation",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "employment"

    def test_wages_payment_title(self, classifier):
        """Test 'Wages Payment' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Wages Payment and Distribution",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "employment"

    def test_mandays_generation_title(self, classifier):
        """Test 'Man-days Generation' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_003",
                "toc_entry": "Man-days Generation under MGNREGA",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "employment"


class TestExecutionPatterns:
    """Test P0-09 execution section patterns."""

    def test_execution_of_works_title(self, classifier):
        """Test 'Execution of Works' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Execution of Works",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "execution"

    def test_implementation_of_scheme_title(self, classifier):
        """Test 'Implementation of Scheme' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Implementation of the Scheme",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "execution"

    def test_contract_management_title(self, classifier):
        """Test 'Contract Management' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_003",
                "toc_entry": "Contract Management",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "execution"


class TestPlanningPatterns:
    """Test P0-09 planning section patterns."""

    def test_planning_deficiencies_title(self, classifier):
        """Test 'Deficiencies in Planning' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Deficiencies in Planning",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "planning"

    def test_action_plan_title(self, classifier):
        """Test 'Action Plan' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Annual Action Plan",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "planning"


class TestMonitoringEvaluationPatterns:
    """Test P0-09 monitoring and evaluation section patterns."""

    def test_monitoring_evaluation_title(self, classifier):
        """Test 'Monitoring and Evaluation' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Monitoring and Evaluation",
                "hierarchy": {},
            }
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "monitoring_evaluation"
        )

    def test_internal_audit_title(self, classifier):
        """Test 'Internal Audit' title classification."""
        chunks = [
            {"chunk_id": "chunk_002", "toc_entry": "Internal Audit", "hierarchy": {}}
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "monitoring_evaluation"
        )

    def test_performance_monitoring_title(self, classifier):
        """Test 'Performance Monitoring' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_003",
                "toc_entry": "Performance Monitoring and Review",
                "hierarchy": {},
            }
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "monitoring_evaluation"
        )


class TestCapacityBuildingPatterns:
    """Test P0-09 capacity building section patterns."""

    def test_capacity_building_title(self, classifier):
        """Test 'Capacity Building' title classification."""
        chunks = [
            {"chunk_id": "chunk_001", "toc_entry": "Capacity Building", "hierarchy": {}}
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "capacity_building"

    def test_training_development_title(self, classifier):
        """Test 'Training and Development' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Training and Capacity Development",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "capacity_building"


class TestGrievanceRedressalPatterns:
    """Test P0-09 grievance redressal section patterns."""

    def test_grievance_redressal_title(self, classifier):
        """Test 'Grievance Redressal' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Grievance Redressal",
                "hierarchy": {},
            }
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "grievance_redressal"
        )

    def test_complaint_handling_title(self, classifier):
        """Test 'Complaint Handling' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Complaint Handling Mechanism",
                "hierarchy": {},
            }
        ]
        assert (
            classifier.classify_topic(chunks[0]["toc_entry"]) == "grievance_redressal"
        )


class TestImpactPatterns:
    """Test P0-09 impact section patterns."""

    def test_impact_assessment_title(self, classifier):
        """Test 'Impact Assessment' title classification."""
        chunks = [
            {"chunk_id": "chunk_001", "toc_entry": "Impact Assessment", "hierarchy": {}}
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "impact"

    def test_outcome_evaluation_title(self, classifier):
        """Test 'Outcome Evaluation' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Outcome Analysis and Evaluation",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "impact"


class TestInfrastructurePatterns:
    """Test P0-09 infrastructure section patterns."""

    def test_infrastructure_development_title(self, classifier):
        """Test 'Infrastructure Development' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Infrastructure Development",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "infrastructure"

    def test_solid_waste_management_title(self, classifier):
        """Test 'Solid Waste Management' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Solid Waste Management",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "infrastructure"


class TestServiceDeliveryPatterns:
    """Test P0-09 service delivery section patterns."""

    def test_service_delivery_title(self, classifier):
        """Test 'Service Delivery' title classification."""
        chunks = [
            {"chunk_id": "chunk_001", "toc_entry": "Service Delivery", "hierarchy": {}}
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "service_delivery"

    def test_benefit_delivery_title(self, classifier):
        """Test 'Benefit Delivery' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Benefit Delivery and Distribution",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "service_delivery"


class TestEnvironmentPatterns:
    """Test P0-09 environment section patterns."""

    def test_environmental_management_title(self, classifier):
        """Test 'Environmental Management' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "toc_entry": "Environmental Management",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "environment"

    def test_pollution_control_title(self, classifier):
        """Test 'Pollution Control' title classification."""
        chunks = [
            {
                "chunk_id": "chunk_002",
                "toc_entry": "Pollution Control and Prevention",
                "hierarchy": {},
            }
        ]
        assert classifier.classify_topic(chunks[0]["toc_entry"]) == "environment"


class TestOtherRatioCalculation:
    """Test calculation of 'other' ratio for classification quality assessment."""

    def test_low_other_ratio(self, classifier):
        """A report with chapter structure leaves nothing as 'other'."""
        chunks = [
            {
                "chunk_id": "c1",
                "toc_entry": "Executive Summary",
                "toc_level": 1,
                "hierarchy": {},
            },
            {
                "chunk_id": "c2",
                "toc_entry": "Chapter 1 Introduction",
                "toc_level": 1,
                "hierarchy": {},
            },
            {
                "chunk_id": "c3",
                "toc_entry": "Chapter 2 Financial Management",
                "toc_level": 1,
                "hierarchy": {},
            },
            {
                "chunk_id": "c4",
                "toc_entry": "2.1 Monitoring and Evaluation",
                "toc_level": 2,
                "hierarchy": {
                    "level_1": "Chapter 2 Financial Management",
                    "level_2": "2.1 Monitoring and Evaluation",
                },
            },
            {
                "chunk_id": "c5",
                "toc_entry": "2.2 Recommendations",
                "toc_level": 2,
                "hierarchy": {
                    "level_1": "Chapter 2 Financial Management",
                    "level_2": "2.2 Recommendations",
                },
            },
            {
                "chunk_id": "c6",
                "toc_entry": "Chapter 3 Conclusion",
                "toc_level": 1,
                "hierarchy": {},
            },
            {
                "chunk_id": "c7",
                "toc_entry": "Annexure",
                "toc_level": 1,
                "hierarchy": {},
            },
        ]
        results = classifier.classify_sections(chunks)
        assert [r.section_type for r in results] == [
            "executive_summary",
            "introduction",
            "findings",
            "findings",
            "recommendations",
            "conclusion",
            "annexure",
        ]

    def test_high_other_ratio_for_unrecognized_sections(self, classifier):
        """Test that unrecognized sections get 'other' classification."""
        chunks = [
            {
                "chunk_id": "c1",
                "toc_entry": "Some Random Section Title",
                "hierarchy": {},
            },
            {"chunk_id": "c2", "toc_entry": "Another Unknown Heading", "hierarchy": {}},
            {"chunk_id": "c3", "toc_entry": "XYZ ABC Details", "hierarchy": {}},
        ]
        results = classifier.classify_sections(chunks)
        other_count = sum(1 for r in results if r.section_type == "other")
        # All should be 'other', flagged low confidence
        assert other_count == 3
        assert all(r.is_low_confidence for r in results)


class TestMixedSectionClassification:
    """Test classification with mix of roles and topics."""

    def test_mixed_classification(self, classifier):
        """Roles from titles; topics from the topical patterns."""
        chunks = [
            {"chunk_id": "c1", "toc_entry": "Executive Summary", "hierarchy": {}},
            {"chunk_id": "c2", "toc_entry": "Recommendations", "hierarchy": {}},
        ]
        results = classifier.classify_sections(chunks)
        assert [r.section_type for r in results] == [
            "executive_summary",
            "recommendations",
        ]
        assert (
            classifier.classify_topic("Financial Management") == "financial_management"
        )
        assert classifier.classify_topic("Employment Generation") == "employment"
        assert (
            classifier.classify_topic("Monitoring and Evaluation")
            == "monitoring_evaluation"
        )
