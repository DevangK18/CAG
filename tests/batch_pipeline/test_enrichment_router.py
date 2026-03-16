"""
Unit tests for EnrichmentRouter (P2-1).

Tests routing logic that decides which chunks need LLM enrichment
and routes them to appropriate providers (OpenAI vs Anthropic).
"""

import pytest
from src.batch_pipeline.enrichment.enrichment_router import (
    EnrichmentRouter,
    EnrichmentTask,
    RoutingDecision,
)


class TestEnrichmentRouter:
    """Test suite for EnrichmentRouter."""

    def setup_method(self):
        """Create router instance for each test."""
        self.router = EnrichmentRouter(report_type="compliance")

    # ==================== SKIP RULES TESTS ====================

    def test_skip_table_chunks(self):
        """Tables should be skipped (already structured in Phase 1)."""
        chunks = [
            {
                "chunk_id": "table_001",
                "content": "| Year | Amount |\n|------|--------|\n| 2020 | 100 |",
                "content_type": "table_markdown",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "skip"
        assert "already structured" in decisions[0].reason.lower()

    def test_skip_existing_findings(self):
        """Chunks with existing findings should be skipped."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": "The audit revealed irregular expenditure of ₹100 crore.",
                "content_type": "text",
            }
        ]

        existing_findings = [
            {
                "finding_id": "f001",
                "source_chunk_id": "chunk_001",
            }
        ]

        decisions = self.router.route_chunks(chunks, existing_findings)

        assert len(decisions) == 1
        assert decisions[0].provider == "skip"
        assert "already extracted" in decisions[0].reason.lower()

    def test_skip_short_content(self):
        """Very short content (<50 chars) should be skipped."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": "See annexure A.",
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "skip"
        assert "too short" in decisions[0].reason.lower()

    # ==================== ROUTING TESTS ====================

    def test_route_explicit_finding_to_openai(self):
        """Explicit finding signals should route to OpenAI."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": """
                The audit revealed that the department incurred irregular 
                expenditure of ₹847.71 crore without proper authorization.
                This resulted in loss to the exchequer.
                """,
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "openai"
        assert decisions[0].task == EnrichmentTask.FINDING_EXTRACTION
        assert decisions[0].confidence_score > 0.3

    def test_route_implicit_finding_to_openai(self):
        """Implicit signals should route to OpenAI."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": """
                The variance between budget allocation (₹500 crore) and 
                actual expenditure (₹620 crore) amounted to ₹120 crore.
                Reconciliation of accounts has been pending since FY 2019-20.
                """,
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "openai"
        # Could be FINDING_EXTRACTION or IMPLICIT_FINDING depending on scores
        assert decisions[0].task in [
            EnrichmentTask.FINDING_EXTRACTION,
            EnrichmentTask.IMPLICIT_FINDING,
        ]

    def test_route_complex_analysis_to_anthropic(self):
        """Complex analysis signals should route to Anthropic."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": """
                A systematic issue was observed across multiple departments
                where recurring instances of non-compliance with procurement
                procedures led to policy implications requiring regulatory
                changes to address the root cause of these systemic failures.
                """,
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "anthropic"
        assert decisions[0].task == EnrichmentTask.COMPLEX_ANALYSIS
        assert decisions[0].confidence_score > 0.4

    def test_route_entity_signals_to_openai(self):
        """Entity-rich content should route to OpenAI."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": """
                The Ministry of Railways implemented the Pradhan Mantri
                Gram Sadak Yojana in coordination with the Government of
                Uttar Pradesh and National Highways Authority of India.
                """,
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "openai"
        # Could be entity extraction or finding extraction
        assert decisions[0].task in [
            EnrichmentTask.ENTITY_EXTRACTION,
            EnrichmentTask.FINDING_EXTRACTION,
        ]

    def test_skip_low_value_content(self):
        """Content with no signals should be skipped."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": """
                This chapter provides background information about the
                organizational structure and administrative setup. The
                objectives and scope of the audit are described below.
                """,
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "skip"
        assert "no enrichment signals" in decisions[0].reason.lower()

    # ==================== STATISTICS TESTS ====================

    def test_routing_statistics(self):
        """Verify statistics calculation."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": "The audit revealed loss of ₹100 crore.",
                "content_type": "text",
            },
            {
                "chunk_id": "chunk_002",
                "content": "Systematic failures across departments.",
                "content_type": "text",
            },
            {
                "chunk_id": "table_001",
                "content": "| Year | Amount |",
                "content_type": "table_markdown",
            },
        ]

        decisions = self.router.route_chunks(chunks, [])
        stats = self.router.get_routing_statistics(decisions)

        assert stats["total_chunks"] == 3
        assert stats["by_provider"]["skip"] >= 1  # At least the table
        assert "by_task" in stats
        assert "average_confidence" in stats

    # ==================== BATCH PROCESSING TESTS ====================

    def test_multiple_chunks_routing(self):
        """Test routing multiple chunks at once."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": "The audit revealed irregular expenditure of ₹100 crore.",
                "content_type": "text",
            },
            {
                "chunk_id": "chunk_002",
                "content": "Variance of ₹50 crore between budget and actual.",
                "content_type": "text",
            },
            {
                "chunk_id": "chunk_003",
                "content": "Systematic issue across multiple departments.",
                "content_type": "text",
            },
            {
                "chunk_id": "table_001",
                "content": "| Year | Amount |",
                "content_type": "table_markdown",
            },
            {
                "chunk_id": "chunk_004",
                "content": "See previous section.",
                "content_type": "text",
            },
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 5

        # Verify each gets routed
        providers = [d.provider for d in decisions]
        assert "openai" in providers  # At least one goes to OpenAI
        assert "skip" in providers  # Table and short content should skip

    def test_report_type_routing(self):
        """Test that report type is used in routing decisions."""
        compliance_router = EnrichmentRouter(report_type="compliance")
        performance_router = EnrichmentRouter(report_type="performance")

        # Both should route the same chunk
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": "The audit revealed non-compliance with financial rules.",
                "content_type": "text",
            }
        ]

        compliance_decisions = compliance_router.route_chunks(chunks, [])
        performance_decisions = performance_router.route_chunks(chunks, [])

        # Both should route to some provider
        assert compliance_decisions[0].provider in ["openai", "anthropic"]
        assert performance_decisions[0].provider in ["openai", "anthropic"]

    # ==================== EDGE CASES ====================

    def test_empty_chunks_list(self):
        """Test with empty chunks list."""
        decisions = self.router.route_chunks([], [])
        assert len(decisions) == 0

    def test_chunk_without_content(self):
        """Test chunk with missing content field."""
        chunks = [{"chunk_id": "chunk_001", "content_type": "text"}]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "skip"

    def test_chunk_with_empty_content(self):
        """Test chunk with empty content."""
        chunks = [
            {
                "chunk_id": "chunk_001",
                "content": "",
                "content_type": "text",
            }
        ]

        decisions = self.router.route_chunks(chunks, [])

        assert len(decisions) == 1
        assert decisions[0].provider == "skip"


class TestPatternScoring:
    """Test pattern scoring logic."""

    def setup_method(self):
        """Create router for testing."""
        self.router = EnrichmentRouter()

    def test_finding_patterns(self):
        """Test finding pattern matching."""
        text = "The audit revealed non-compliance with rules."
        score = self.router._score_patterns(text, self.router.finding_patterns)
        assert score > 0

    def test_implicit_patterns(self):
        """Test implicit pattern matching."""
        text = "Variance of ₹50 crore against target."
        score = self.router._score_patterns(text, self.router.implicit_patterns)
        assert score > 0

    def test_complex_patterns(self):
        """Test complex pattern matching."""
        text = "Systematic issue across multiple departments."
        score = self.router._score_patterns(text, self.router.complex_patterns)
        assert score > 0

    def test_no_pattern_match(self):
        """Test text with no pattern matches."""
        text = "This is just background information."
        score = self.router._score_patterns(text, self.router.finding_patterns)
        assert score == 0

    def test_multiple_pattern_matches(self):
        """Test text matching multiple patterns."""
        text = """
        The audit revealed irregular expenditure and non-compliance.
        Loss of ₹100 crore was observed due to unauthorized spending.
        """
        score = self.router._score_patterns(text, self.router.finding_patterns)
        # Should match multiple patterns
        assert score > 0.3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
