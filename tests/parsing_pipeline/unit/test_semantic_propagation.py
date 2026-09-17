"""
Tests for Semantic Enrichment Propagation to Chunks
=====================================================

Tests the propagate_semantic_enrichment_to_chunks function that bridges
document-level semantic extraction with chunk-level Qdrant indexing.

Run: pytest tests/parsing_pipeline/unit/test_semantic_propagation.py -v
"""

import pytest
from typing import Dict, List, Any


# Import the function under test
from src.parsing_pipeline.modules.assembly_service import (
    propagate_semantic_enrichment_to_chunks,
)


@pytest.fixture
def sample_child_chunks() -> List[Dict[str, Any]]:
    """Sample child chunks for testing."""
    return [
        {
            "chunk_id": "report_001_child_p010_paragraph_001",
            "parent_chunk_id": "report_001_parent_L2_001",
            "content_type": "paragraph",
            "content": "The Ministry of Railways failed to collect ₹847.71 crore in toll revenue.",
            "structured_data": None,
        },
        {
            "chunk_id": "report_001_child_p015_paragraph_002",
            "parent_chunk_id": "report_001_parent_L2_002",
            "content_type": "paragraph",
            "content": "Audit recommends that NHAI should implement better monitoring systems.",
            "structured_data": {},
        },
        {
            "chunk_id": "report_001_child_p020_table_001",
            "parent_chunk_id": "report_001_parent_L2_003",
            "content_type": "table_markdown",
            "content": "| Item | Amount |\n|------|--------|\n| Loss | 100 cr |",
            "structured_data": {"rows": 2, "cols": 2},
        },
        {
            "chunk_id": "report_001_child_p025_paragraph_003",
            "parent_chunk_id": "report_001_parent_L2_001",
            "content_type": "paragraph",
            "content": "Regular monitoring was not conducted by the department.",
            "structured_data": None,
        },
    ]


@pytest.fixture
def sample_semantic_enrichment() -> Dict[str, Any]:
    """Sample semantic enrichment data."""
    return {
        "report_id": "report_001",
        "findings": [
            {
                "finding_id": "report_001_finding_001",
                "finding_type": "loss_of_revenue",
                "severity": "critical",
                "source_chunk_id": "report_001_child_p010_paragraph_001",
                "monetary_value_crore": 847.71,
                "total_amount_inr": 8477100000000,  # in paise
                "entities_mentioned": ["Ministry of Railways", "NHAI"],
                "text": "The Ministry of Railways failed to collect ₹847.71 crore.",
            },
            {
                "finding_id": "report_001_finding_002",
                "finding_type": "non_compliance",
                "severity": "high",
                "source_chunk_id": "report_001_child_p025_paragraph_003",
                "monetary_value_crore": None,
                "total_amount_inr": 0,
                "entities_mentioned": [],
                "text": "Regular monitoring was not conducted.",
            },
        ],
        "recommendations": [
            {
                "recommendation_id": "report_001_rec_001",
                "source_chunk_id": "report_001_child_p015_paragraph_002",
                "target_entity": "NHAI",
                "text": "NHAI should implement better monitoring systems.",
            },
        ],
        "section_classifications": [
            {
                "parent_chunk_id": "report_001_parent_L2_001",
                "section_type": "audit_findings",
            },
            {
                "parent_chunk_id": "report_001_parent_L2_002",
                "section_type": "recommendations",
            },
            {
                "parent_chunk_id": "report_001_parent_L2_003",
                "section_type": "annexures",
            },
        ],
        "entities": {
            "schemes": ["Bharatmala Pariyojana"],
            "ministries": ["Ministry of Road Transport"],
            "organizations": ["NHAI", "FCI"],
        },
    }


class TestPropagateSemanticEnrichmentBasics:
    """Basic functionality tests."""

    def test_propagate_returns_counts(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that function returns correct propagation counts."""
        findings, recs, entities = propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        assert findings == 2, "Should propagate 2 findings"
        assert recs == 1, "Should propagate 1 recommendation"
        assert entities >= 1, "Should propagate at least 1 entity annotation"

    def test_propagate_empty_enrichment(self, sample_child_chunks):
        """Test with empty semantic enrichment."""
        findings, recs, entities = propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, {}
        )

        assert findings == 0
        assert recs == 0
        assert entities == 0

    def test_propagate_none_enrichment(self, sample_child_chunks):
        """Test with None semantic enrichment."""
        findings, recs, entities = propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, None
        )

        assert findings == 0
        assert recs == 0
        assert entities == 0


class TestPropagateFindings:
    """Tests for finding propagation."""

    def test_finding_type_propagated(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that finding_type is propagated to chunks."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        # First chunk should have loss_of_revenue
        chunk_1 = sample_child_chunks[0]
        assert chunk_1["structured_data"]["finding_type"] == "loss_of_revenue"

        # Fourth chunk should have non_compliance
        chunk_4 = sample_child_chunks[3]
        assert chunk_4["structured_data"]["finding_type"] == "non_compliance"

    def test_severity_propagated(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that severity is propagated to chunks."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_1 = sample_child_chunks[0]
        assert chunk_1["structured_data"]["severity"] == "critical"

        chunk_4 = sample_child_chunks[3]
        assert chunk_4["structured_data"]["severity"] == "high"

    def test_monetary_values_propagated(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that monetary values are propagated."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_1 = sample_child_chunks[0]
        assert chunk_1["structured_data"]["total_amount_crore"] == 847.71
        assert chunk_1["structured_data"]["total_amount_inr"] == 8477100000000

    def test_is_finding_flag_set(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that is_finding flag is set."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_1 = sample_child_chunks[0]
        assert chunk_1["structured_data"]["is_finding"] is True

        # Chunk without finding should not have is_finding
        chunk_2 = sample_child_chunks[1]
        assert chunk_2["structured_data"].get("is_finding") is None or \
               chunk_2["structured_data"].get("is_finding") is False

    def test_finding_ids_stored(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that finding IDs are stored in chunk."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_1 = sample_child_chunks[0]
        assert "report_001_finding_001" in chunk_1["structured_data"]["finding_ids"]

    def test_entities_from_finding_propagated(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that entities from findings are propagated."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_1 = sample_child_chunks[0]
        entities = chunk_1["structured_data"].get("entities_mentioned", [])
        assert "Ministry of Railways" in entities
        assert "NHAI" in entities


class TestPropagateRecommendations:
    """Tests for recommendation propagation."""

    def test_is_recommendation_flag_set(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that is_recommendation flag is set."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_2 = sample_child_chunks[1]
        assert chunk_2["structured_data"]["is_recommendation"] is True

    def test_recommendation_target_propagated(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that recommendation target is propagated."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_2 = sample_child_chunks[1]
        assert chunk_2["structured_data"]["recommendation_target"] == "NHAI"

    def test_recommendation_ids_stored(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that recommendation IDs are stored."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        chunk_2 = sample_child_chunks[1]
        assert "report_001_rec_001" in chunk_2["structured_data"]["recommendation_ids"]


class TestPropagateSectionTypes:
    """Tests for section type propagation."""

    def test_section_type_from_parent(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that section_type is inherited from parent."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        # Chunk 1 and 4 share parent L2_001 which is audit_findings
        chunk_1 = sample_child_chunks[0]
        assert chunk_1["structured_data"]["section_type"] == "audit_findings"

        chunk_4 = sample_child_chunks[3]
        assert chunk_4["structured_data"]["section_type"] == "audit_findings"

        # Chunk 2 has parent L2_002 which is recommendations
        chunk_2 = sample_child_chunks[1]
        assert chunk_2["structured_data"]["section_type"] == "recommendations"


class TestPropagateEntities:
    """Tests for entity mention propagation."""

    def test_entity_matching_in_content(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test that entities mentioned in content are detected."""
        propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        # Chunk 2 mentions NHAI in content
        chunk_2 = sample_child_chunks[1]
        entities = chunk_2["structured_data"].get("entities_mentioned", [])
        assert "NHAI" in entities

    def test_entity_cap_at_10(self, sample_child_chunks):
        """Test that entities are capped at 10."""
        # Create enrichment with many entities
        enrichment = {
            "entities": {
                "schemes": [f"Scheme_{i}" for i in range(15)],
                "ministries": [],
                "organizations": [],
            },
            "findings": [],
            "recommendations": [],
            "section_classifications": [],
        }

        # Create chunk that mentions all schemes
        sample_child_chunks[0]["content"] = " ".join(
            [f"Scheme_{i}" for i in range(15)]
        )

        propagate_semantic_enrichment_to_chunks(sample_child_chunks, enrichment)

        chunk_1 = sample_child_chunks[0]
        entities = chunk_1["structured_data"].get("entities_mentioned", [])
        assert len(entities) <= 10


class TestPropagateEdgeCases:
    """Edge case tests."""

    def test_preserves_existing_structured_data(self):
        """Test that existing structured_data fields are preserved."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "parent_chunk_id": "parent_001",
                "content": "Test content",
                "structured_data": {"existing_field": "preserved"},
            }
        ]

        enrichment = {
            "findings": [
                {
                    "finding_id": "f1",
                    "finding_type": "loss_of_revenue",
                    "severity": "high",
                    "source_chunk_id": "chunk_001",
                }
            ],
            "recommendations": [],
            "section_classifications": [],
            "entities": {},
        }

        propagate_semantic_enrichment_to_chunks(chunks, enrichment)

        # Existing field should be preserved
        assert chunks[0]["structured_data"]["existing_field"] == "preserved"
        # New field should be added
        assert chunks[0]["structured_data"]["finding_type"] == "loss_of_revenue"

    def test_handles_missing_source_chunk_id(self):
        """Test handling of findings without source_chunk_id."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "parent_chunk_id": "parent_001",
                "content": "Test",
            }
        ]

        enrichment = {
            "findings": [
                {
                    "finding_id": "f1",
                    "finding_type": "loss_of_revenue",
                    # No source_chunk_id
                }
            ],
            "recommendations": [],
            "section_classifications": [],
            "entities": {},
        }

        # Should not raise
        findings, recs, entities = propagate_semantic_enrichment_to_chunks(
            chunks, enrichment
        )
        assert findings == 0  # Not propagated since no source_chunk_id

    def test_multiple_findings_same_chunk(self):
        """Test handling multiple findings pointing to same chunk."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "parent_chunk_id": "parent_001",
                "content": "Multiple findings here",
            }
        ]

        enrichment = {
            "findings": [
                {
                    "finding_id": "f1",
                    "finding_type": "loss_of_revenue",
                    "severity": "critical",
                    "source_chunk_id": "chunk_001",
                },
                {
                    "finding_id": "f2",
                    "finding_type": "non_compliance",
                    "severity": "high",
                    "source_chunk_id": "chunk_001",
                },
            ],
            "recommendations": [],
            "section_classifications": [],
            "entities": {},
        }

        propagate_semantic_enrichment_to_chunks(chunks, enrichment)

        # Primary finding (first) should set type/severity
        assert chunks[0]["structured_data"]["finding_type"] == "loss_of_revenue"
        assert chunks[0]["structured_data"]["severity"] == "critical"

        # Both finding IDs should be stored
        assert "f1" in chunks[0]["structured_data"]["finding_ids"]
        assert "f2" in chunks[0]["structured_data"]["finding_ids"]


class TestPropagateIntegration:
    """Integration tests with realistic data."""

    def test_full_propagation_realistic(
        self, sample_child_chunks, sample_semantic_enrichment
    ):
        """Test complete propagation with realistic data."""
        findings, recs, entities = propagate_semantic_enrichment_to_chunks(
            sample_child_chunks, sample_semantic_enrichment
        )

        # Verify counts
        assert findings == 2
        assert recs == 1

        # Verify first chunk (finding with monetary)
        chunk_1 = sample_child_chunks[0]
        sd_1 = chunk_1["structured_data"]
        assert sd_1["finding_type"] == "loss_of_revenue"
        assert sd_1["severity"] == "critical"
        assert sd_1["total_amount_crore"] == 847.71
        assert sd_1["is_finding"] is True
        assert sd_1["section_type"] == "audit_findings"
        assert "Ministry of Railways" in sd_1["entities_mentioned"]

        # Verify second chunk (recommendation)
        chunk_2 = sample_child_chunks[1]
        sd_2 = chunk_2["structured_data"]
        assert sd_2["is_recommendation"] is True
        assert sd_2["recommendation_target"] == "NHAI"
        assert sd_2["section_type"] == "recommendations"

        # Verify third chunk (table - no finding/rec)
        chunk_3 = sample_child_chunks[2]
        sd_3 = chunk_3["structured_data"]
        assert sd_3.get("is_finding") is None
        assert sd_3.get("is_recommendation") is None
        assert sd_3["section_type"] == "annexures"

        # Verify fourth chunk (finding without monetary)
        chunk_4 = sample_child_chunks[3]
        sd_4 = chunk_4["structured_data"]
        assert sd_4["finding_type"] == "non_compliance"
        assert sd_4["severity"] == "high"
        assert sd_4.get("total_amount_crore") is None
        assert sd_4["is_finding"] is True
