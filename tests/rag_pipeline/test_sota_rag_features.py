"""
Tests for SOTA RAG Features.

Tests cover:
- Query Router (Feature 2)
- Self-RAG / Retrieval Decider (Feature 3)
- Corrective RAG (Feature 4)
- Hierarchical Retrieval (Feature 1)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

# Import SOTA RAG components
from src.rag_pipeline.query_router import (
    QueryRouter,
    QueryRoute,
    RoutingDecision,
)
from src.rag_pipeline.retrieval_decider import (
    RetrievalDecider,
    RetrievalDecision,
    DecisionResult,
    ParametricResponder,
)
from src.rag_pipeline.corrective_rag import (
    RelevanceChecker,
    QueryReformulator,
    CitationValidator,
    CorrectiveRAGService,
    RelevanceAssessment,
    CitationValidation,
)
from src.rag_pipeline.hierarchical_retriever import (
    HierarchicalRetriever,
    is_overview_query,
    get_recommended_level,
)
from src.core.config import (
    QueryRoutingConfig,
    SelfRAGConfig,
    CorrectiveRAGConfig,
    HierarchicalConfig,
)


# =============================================================================
# QUERY ROUTER TESTS
# =============================================================================


class TestQueryRouter:
    """Tests for Query Router (SOTA Feature 2)."""

    @pytest.fixture
    def config(self):
        return QueryRoutingConfig(
            enabled=True,
            min_confidence=0.7,
        )

    @pytest.fixture
    def router(self, config):
        return QueryRouter(config=config, openai_client=None)

    def test_temporal_routing(self, router):
        """Test routing for temporal queries."""
        queries = [
            "How has FRBM compliance changed from 2020 to 2024?",
            "What is the trend in toll revenue?",
            "Compare year over year performance",
        ]
        for query in queries:
            decision = router.route(query)
            assert decision.route == QueryRoute.TEMPORAL
            assert decision.confidence >= 0.7

    def test_summary_routing(self, router):
        """Test routing for summary/overview queries."""
        queries = [
            "Summarize the main themes",
            "Give me an overview of the findings",
            "What are the key issues?",
        ]
        for query in queries:
            decision = router.route(query)
            assert decision.route == QueryRoute.SUMMARY_ONLY
            assert decision.confidence >= 0.7

    def test_entity_comparison_routing(self, router):
        """Test routing for entity comparison queries."""
        queries = [
            "Compare Railways vs NHAI findings",
            "Which ministry has the most irregularities?",
        ]
        for query in queries:
            decision = router.route(query)
            assert decision.route == QueryRoute.ENTITY_COMPARATIVE

    def test_filtered_search_routing(self, router):
        """Test routing for filtered search queries."""
        queries = [
            "All GST issues in Gujarat",
            "Show me all revenue losses in Maharashtra",
        ]
        for query in queries:
            decision = router.route(query)
            assert decision.route == QueryRoute.FILTERED_SEARCH

    def test_standard_rag_routing(self, router):
        """Test fallback to standard RAG for factual queries."""
        query = "What was the revenue loss at Nathavalasa toll plaza?"
        decision = router.route(query)
        # Should fall back to standard RAG without LLM
        assert decision.route == QueryRoute.STANDARD_RAG

    def test_state_extraction(self, router):
        """Test state name extraction from queries."""
        state = router._extract_state("issues in Gujarat state")
        assert state == "Gujarat"

        state = router._extract_state("findings from Maharashtra")
        assert state == "Maharashtra"

    def test_year_extraction(self, router):
        """Test year extraction from queries."""
        years = router._extract_years("findings from 2023-24")
        assert "2023-24" in years

        years = router._extract_years("compare 2020 to 2024")
        assert "2020" in years
        assert "2024" in years

    def test_hierarchy_level_detection(self, router):
        """Test hierarchy level detection for summary queries."""
        # Report level
        level = router._detect_hierarchy_level("summarize the entire report")
        assert level == 3

        # Section level
        level = router._detect_hierarchy_level("specific section findings")
        assert level == 1

        # Default chapter level
        level = router._detect_hierarchy_level("main findings")
        assert level == 2


# =============================================================================
# SELF-RAG / RETRIEVAL DECIDER TESTS
# =============================================================================


class TestRetrievalDecider:
    """Tests for Self-RAG / Retrieval Decider (SOTA Feature 3)."""

    @pytest.fixture
    def config(self):
        return SelfRAGConfig(enabled=True)

    @pytest.fixture
    def decider(self, config):
        return RetrievalDecider(config)

    def test_skip_definitional_queries(self, decider):
        """Test skipping retrieval for definitional queries."""
        queries = [
            "What is CAG?",
            "What does FRBM stand for?",
            "Define compliance audit",
        ]
        for query in queries:
            decision = decider.decide(query)
            assert decision.decision == RetrievalDecision.SKIP
            assert decision.confidence >= 0.9

    def test_parametric_answers_for_acronyms(self, decider):
        """Test parametric answers are provided for acronyms."""
        decision = decider.decide("What is CAG?")
        assert decision.decision == RetrievalDecision.SKIP
        assert decision.parametric_answer is not None
        assert "Comptroller" in decision.parametric_answer

    def test_require_retrieval_for_specific_queries(self, decider):
        """Test retrieval is required for specific queries."""
        queries = [
            "What was the revenue loss at Nathavalasa toll plaza?",
            "How much money was lost in 2023?",
            "₹500 crore toll collection issue",
        ]
        for query in queries:
            decision = decider.decide(query)
            assert decision.decision == RetrievalDecision.RETRIEVE

    def test_multi_retrieve_for_complex_queries(self, decider):
        """Test multi-retrieve is suggested for complex queries."""
        queries = [
            "What caused the delay and what were the effects on revenue?",
            "Analyze performance across NHAI and Railways and FCI",
        ]
        for query in queries:
            decision = decider.decide(query)
            assert decision.decision == RetrievalDecision.MULTI_RETRIEVE

    def test_helper_methods(self, decider):
        """Test helper methods."""
        assert decider.should_skip_retrieval("What is CAG?") is True
        assert decider.should_skip_retrieval("toll plaza findings") is False

        assert decider.should_use_agentic("compare and analyze multiple factors") is True


class TestParametricResponder:
    """Tests for parametric response generation."""

    @pytest.fixture
    def responder(self):
        return ParametricResponder(llm_client=None)

    def test_fallback_response_for_cag(self, responder):
        """Test fallback response for CAG queries."""
        response = responder.respond("What is CAG?")
        assert "Comptroller" in response
        assert "Auditor" in response

    def test_fallback_response_for_frbm(self, responder):
        """Test fallback response for FRBM queries."""
        response = responder.respond("What is FRBM?")
        assert "Fiscal" in response


# =============================================================================
# CORRECTIVE RAG TESTS
# =============================================================================


class TestRelevanceChecker:
    """Tests for Relevance Checker."""

    @pytest.fixture
    def config(self):
        return CorrectiveRAGConfig(
            min_relevance_score=0.25,
            min_relevant_chunks=3,
        )

    @pytest.fixture
    def checker(self, config):
        return RelevanceChecker(config)

    def test_sufficient_relevance(self, checker):
        """Test detection of sufficient relevance."""
        # Create mock retrieval result with good scores
        mock_result = Mock()
        mock_chunks = [
            Mock(score=0.8, chunk_id="c1"),
            Mock(score=0.6, chunk_id="c2"),
            Mock(score=0.5, chunk_id="c3"),
            Mock(score=0.3, chunk_id="c4"),
        ]
        mock_parent = Mock(children=mock_chunks)
        mock_result.parents = [mock_parent]

        assessment = checker.check("test query", mock_result)
        assert assessment.is_sufficient is True
        assert assessment.suggestion == "sufficient"
        assert assessment.relevant_count == 4

    def test_insufficient_relevance_reformulate(self, checker):
        """Test detection of insufficient relevance - reformulate."""
        # Create mock retrieval result with poor scores
        mock_result = Mock()
        mock_chunks = [
            Mock(score=0.15, chunk_id="c1"),
            Mock(score=0.1, chunk_id="c2"),
        ]
        mock_parent = Mock(children=mock_chunks)
        mock_result.parents = [mock_parent]

        assessment = checker.check("test query", mock_result)
        assert assessment.is_sufficient is False
        assert assessment.suggestion == "reformulate"

    def test_empty_results(self, checker):
        """Test handling of empty results."""
        mock_result = Mock()
        mock_result.parents = []

        assessment = checker.check("test query", mock_result)
        assert assessment.is_sufficient is False
        assert assessment.relevant_count == 0


class TestQueryReformulator:
    """Tests for Query Reformulator."""

    @pytest.fixture
    def config(self):
        return CorrectiveRAGConfig()

    @pytest.fixture
    def reformulator(self, config):
        return QueryReformulator(config, openai_client=None)

    def test_rule_based_reformulation(self, reformulator):
        """Test rule-based query reformulation."""
        # Test substitution
        result = reformulator._rule_based_reformulation("money lost")
        assert "revenue loss" in result

        result = reformulator._rule_based_reformulation("wasted money")
        assert "infructuous expenditure" in result

    def test_fallback_reformulation(self, reformulator):
        """Test fallback when no rule matches."""
        result = reformulator._rule_based_reformulation("some random query")
        assert "CAG audit finding" in result


class TestCitationValidator:
    """Tests for Citation Validator."""

    @pytest.fixture
    def config(self):
        return CorrectiveRAGConfig(
            validate_citations=True,
            strip_invalid_citations=True,
        )

    @pytest.fixture
    def validator(self, config):
        return CitationValidator(config)

    def test_valid_citations(self, validator):
        """Test validation of valid citations."""
        answer = "Revenue loss of ₹64 crore. [Section 3.2, p.36]"

        # Create mock retrieval result
        mock_result = Mock()
        mock_child = Mock()
        mock_child.page_physical = 35  # p.36 in 1-indexed
        mock_parent = Mock(toc_entry="Section 3.2 Revenue Issues", children=[mock_child])
        mock_result.parents = [mock_parent]

        validation = validator.validate(answer, mock_result)
        assert len(validation.valid_citations) == 1
        assert validation.all_valid is True

    def test_invalid_citation_stripping(self, validator):
        """Test stripping of invalid citations."""
        answer = "Some finding. [Nonexistent Section, p.999]"

        mock_result = Mock()
        mock_result.parents = []

        validation = validator.validate(answer, mock_result)
        assert len(validation.invalid_citations) == 1
        assert "[Nonexistent Section, p.999]" not in validation.cleaned_answer

    def test_no_citations(self, validator):
        """Test handling of answers without citations."""
        answer = "This is an answer without citations."

        mock_result = Mock()
        mock_result.parents = []

        validation = validator.validate(answer, mock_result)
        assert validation.all_valid is True
        assert validation.cleaned_answer == answer


class TestCorrectiveRAGService:
    """Tests for the full Corrective RAG service."""

    @pytest.fixture
    def config(self):
        return CorrectiveRAGConfig(
            max_reformulations=2,
            validate_citations=True,
        )

    @pytest.fixture
    def service(self, config):
        return CorrectiveRAGService(config, openai_client=None)

    def test_sufficient_retrieval_no_correction(self, service):
        """Test that sufficient retrieval doesn't trigger correction."""
        mock_result = Mock()
        mock_chunks = [Mock(score=0.8, chunk_id="c1") for _ in range(5)]
        mock_parent = Mock(children=mock_chunks)
        mock_result.parents = [mock_parent]
        mock_result.total_after_rerank = 5

        # Mock retrieve function that shouldn't be called
        retrieve_fn = Mock()

        result, info = service.check_and_correct_retrieval(
            "test query", mock_result, retrieve_fn
        )

        assert result == mock_result
        assert info["retrieval_attempts"] == 1
        retrieve_fn.assert_not_called()


# =============================================================================
# HIERARCHICAL RETRIEVAL TESTS
# =============================================================================


class TestHierarchicalHelpers:
    """Tests for hierarchical retrieval helper functions."""

    def test_is_overview_query(self):
        """Test overview query detection."""
        assert is_overview_query("Summarize the main themes") is True
        assert is_overview_query("Give me an overview") is True
        assert is_overview_query("key findings in this report") is True

        assert is_overview_query("What was the revenue loss?") is False
        assert is_overview_query("toll plaza issues") is False

    def test_get_recommended_level(self):
        """Test hierarchy level recommendation."""
        # Report level (L3)
        assert get_recommended_level("summarize the entire report") == 3

        # Section level (L1)
        assert get_recommended_level("specific section findings") == 1

        # Standard retrieval (L0)
        assert get_recommended_level("exact amount ₹500 crore") == 0

        # Default chapter level (L2)
        assert get_recommended_level("what are the issues") == 2


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestSOTAIntegration:
    """Integration tests for SOTA features working together."""

    def test_routing_to_self_rag_consistency(self):
        """Test that routing and self-RAG don't conflict."""
        routing_config = QueryRoutingConfig()
        self_rag_config = SelfRAGConfig()

        router = QueryRouter(routing_config, openai_client=None)
        decider = RetrievalDecider(self_rag_config)

        # Definitional query - both should agree to skip retrieval
        query = "What is CAG?"
        routing_decision = router.route(query)
        retrieval_decision = decider.decide(query)

        # Self-RAG should skip, routing shouldn't matter
        assert retrieval_decision.decision == RetrievalDecision.SKIP

    def test_routing_and_corrective_flow(self):
        """Test that routing decisions flow to corrective RAG."""
        routing_config = QueryRoutingConfig()
        corrective_config = CorrectiveRAGConfig()

        router = QueryRouter(routing_config, openai_client=None)
        corrective = CorrectiveRAGService(corrective_config, openai_client=None)

        # A standard RAG query should be checked by corrective
        query = "What was the revenue loss?"
        routing_decision = router.route(query)

        # This would normally flow through the full RAG pipeline
        # and corrective RAG would check relevance
        assert routing_decision.route == QueryRoute.STANDARD_RAG


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestSOTAConfig:
    """Tests for SOTA feature configuration."""

    def test_hierarchical_config_defaults(self):
        """Test HierarchicalConfig defaults."""
        config = HierarchicalConfig()
        assert config.enabled is True
        assert config.drill_down_threshold == 0.85
        assert config.default_level == 2
        assert "haiku" in config.chapter_model

    def test_query_routing_config_defaults(self):
        """Test QueryRoutingConfig defaults."""
        config = QueryRoutingConfig()
        assert config.enabled is True
        assert config.min_confidence == 0.7
        assert config.fallback_on_error is True

    def test_self_rag_config_defaults(self):
        """Test SelfRAGConfig defaults."""
        config = SelfRAGConfig()
        assert config.enabled is True
        assert config.use_llm_classifier is False
        assert len(config.skip_patterns) > 0

    def test_corrective_rag_config_defaults(self):
        """Test CorrectiveRAGConfig defaults."""
        config = CorrectiveRAGConfig()
        assert config.enabled is True
        assert config.min_relevance_score == 0.25
        assert config.max_reformulations == 2
        assert config.validate_citations is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
