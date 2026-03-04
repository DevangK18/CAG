"""
Tests for Query Enhancement Service (Phase 1)
==============================================

Tests the QueryEnhancer single-call query intelligence:
- Question type classification
- Query expansion
- Filter suggestions
- Retrieval parameter recommendations
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import QueryEnhancementConfig
from src.rag_pipeline.query_enhancer import QueryEnhancer, QueryEnhancement


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing."""
    client = Mock()
    client.chat = Mock()
    client.chat.completions = Mock()
    return client


@pytest.fixture
def config():
    """Default query enhancement config."""
    return QueryEnhancementConfig()


@pytest.fixture
def enhancer(config, mock_openai_client):
    """QueryEnhancer instance with mocked client."""
    return QueryEnhancer(config, mock_openai_client)


class TestQueryEnhancerInit:
    """Test QueryEnhancer initialization."""

    def test_init_with_config(self, config, mock_openai_client):
        """Test successful initialization."""
        enhancer = QueryEnhancer(config, mock_openai_client)
        assert enhancer.config == config
        assert enhancer.client == mock_openai_client

    def test_init_with_disabled_config(self, mock_openai_client):
        """Test initialization with disabled enhancement."""
        config = QueryEnhancementConfig(enabled=False)
        enhancer = QueryEnhancer(config, mock_openai_client)
        assert not enhancer.config.enabled


class TestQueryEnhancerFallback:
    """Test fallback behavior when enhancement fails or is disabled."""

    def test_fallback_when_disabled(self, mock_openai_client):
        """Test fallback when enhancement is disabled."""
        config = QueryEnhancementConfig(enabled=False)
        enhancer = QueryEnhancer(config, mock_openai_client)

        result = enhancer.enhance("What are the key findings?")

        assert result.question_type == "factual"
        assert result.expanded_queries == ["What are the key findings?"]
        assert result.suggested_filters == {}
        assert result.top_k == 10
        assert result.initial_candidates == 50
        assert result.max_context_chars == 15000

    def test_fallback_on_exception(self, enhancer, mock_openai_client):
        """Test fallback when LLM call raises exception."""
        mock_openai_client.chat.completions.create.side_effect = Exception(
            "API error"
        )

        result = enhancer.enhance("What are the key findings?")

        assert result.question_type == "factual"
        assert result.expanded_queries == ["What are the key findings?"]
        assert result.suggested_filters == {}


class TestQueryEnhancerEnhance:
    """Test query enhancement with mocked LLM responses."""

    def test_enhance_factual_question(self, enhancer, mock_openai_client):
        """Test enhancement of a factual question."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
        {
          "question_type": "factual",
          "expanded_queries": [
            "CAG audit report key observations",
            "major audit findings reported"
          ],
          "suggested_filters": {},
          "retrieval_params": {
            "top_k": 8,
            "initial_candidates": 30,
            "max_context_chars": 10000
          },
          "recommended_style": "concise"
        }
        """
        mock_openai_client.chat.completions.create.return_value = mock_response

        result = enhancer.enhance("What are the key findings?")

        assert result.question_type == "factual"
        assert len(result.expanded_queries) == 3
        assert result.expanded_queries[0] == "What are the key findings?"
        assert "CAG audit report key observations" in result.expanded_queries
        assert result.top_k == 8
        assert result.initial_candidates == 30
        assert result.max_context_chars == 10000
        assert result.recommended_style == "concise"

    def test_enhance_list_question(self, enhancer, mock_openai_client):
        """Test enhancement of a list question."""
        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
        {
          "question_type": "list",
          "expanded_queries": [
            "enumerate all audit findings",
            "list major observations CAG report"
          ],
          "suggested_filters": {},
          "retrieval_params": {
            "top_k": 18,
            "initial_candidates": 80,
            "max_context_chars": 25000
          },
          "recommended_style": "detailed"
        }
        """
        mock_openai_client.chat.completions.create.return_value = mock_response

        result = enhancer.enhance("List all the key findings")

        assert result.question_type == "list"
        assert result.top_k == 18
        assert result.initial_candidates == 80
        assert result.max_context_chars == 25000
        assert result.recommended_style == "detailed"

    def test_enhance_with_filter_suggestions(self, enhancer, mock_openai_client):
        """Test enhancement with filter suggestions."""
        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
        {
          "question_type": "explanation",
          "expanded_queries": [
            "toll collection revenue loss reasons",
            "why toll revenue shortfall occurred"
          ],
          "suggested_filters": {
            "finding_type": "loss_of_revenue"
          },
          "retrieval_params": {
            "top_k": 12,
            "initial_candidates": 50,
            "max_context_chars": 18000
          },
          "recommended_style": "explanatory"
        }
        """
        mock_openai_client.chat.completions.create.return_value = mock_response

        result = enhancer.enhance("What went wrong with toll collection?")

        assert result.question_type == "explanation"
        assert result.suggested_filters == {"finding_type": "loss_of_revenue"}
        assert result.recommended_style == "explanatory"

    def test_enhance_comparison_question(self, enhancer, mock_openai_client):
        """Test enhancement of a comparison question."""
        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
        {
          "question_type": "comparison",
          "expanded_queries": [
            "fiscal deficit trends across years",
            "year-over-year fiscal deficit changes"
          ],
          "suggested_filters": {},
          "retrieval_params": {
            "top_k": 15,
            "initial_candidates": 60,
            "max_context_chars": 22000
          },
          "recommended_style": "comparative"
        }
        """
        mock_openai_client.chat.completions.create.return_value = mock_response

        result = enhancer.enhance("How has the fiscal deficit changed over the years?")

        assert result.question_type == "comparison"
        assert result.top_k == 15
        assert result.recommended_style == "comparative"

    def test_enhance_with_user_style_override(self, enhancer, mock_openai_client):
        """Test that user-selected style overrides recommendation."""
        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
        {
          "question_type": "factual",
          "expanded_queries": ["query 1", "query 2"],
          "suggested_filters": {},
          "retrieval_params": {
            "top_k": 8,
            "initial_candidates": 30,
            "max_context_chars": 10000
          },
          "recommended_style": "concise"
        }
        """
        mock_openai_client.chat.completions.create.return_value = mock_response

        result = enhancer.enhance("What are the key findings?", style="technical")

        # Should NOT have recommended_style when user overrides
        assert result.recommended_style is None

    def test_enhance_respects_num_expansions_limit(self, enhancer, mock_openai_client):
        """Test that expanded queries are limited by config."""
        config = QueryEnhancementConfig(num_expansions=2)
        enhancer = QueryEnhancer(config, mock_openai_client)

        mock_response = MagicMock()
        mock_response.choices[0].message.content = """
        {
          "question_type": "factual",
          "expanded_queries": ["query 1", "query 2", "query 3", "query 4"],
          "suggested_filters": {},
          "retrieval_params": {
            "top_k": 8,
            "initial_candidates": 30,
            "max_context_chars": 10000
          },
          "recommended_style": "concise"
        }
        """
        mock_openai_client.chat.completions.create.return_value = mock_response

        result = enhancer.enhance("test query")

        # Original + only 1 expansion (limit is 2 total)
        assert len(result.expanded_queries) <= 2
        assert result.expanded_queries[0] == "test query"


class TestQueryEnhancementDataclass:
    """Test QueryEnhancement dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        enhancement = QueryEnhancement(
            question_type="factual",
            expanded_queries=["query"],
            suggested_filters={},
        )

        assert enhancement.top_k == 10
        assert enhancement.initial_candidates == 50
        assert enhancement.max_context_chars == 15000
        assert enhancement.recommended_style is None
        assert enhancement.raw_response is None

    def test_full_initialization(self):
        """Test full initialization with all fields."""
        enhancement = QueryEnhancement(
            question_type="list",
            expanded_queries=["q1", "q2", "q3"],
            suggested_filters={"finding_type": "fraud_misappropriation"},
            top_k=18,
            initial_candidates=80,
            max_context_chars=25000,
            recommended_style="detailed",
            raw_response='{"test": "json"}',
        )

        assert enhancement.question_type == "list"
        assert len(enhancement.expanded_queries) == 3
        assert enhancement.suggested_filters["finding_type"] == "fraud_misappropriation"
        assert enhancement.top_k == 18
        assert enhancement.recommended_style == "detailed"
        assert enhancement.raw_response == '{"test": "json"}'


class TestQueryEnhancementConfig:
    """Test QueryEnhancementConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = QueryEnhancementConfig()

        assert config.enabled is True
        assert config.enable_query_expansion is True
        assert config.enable_passage_reordering is True
        assert config.enable_sufficiency_check is True
        assert config.model == "gpt-4o-mini"
        assert config.max_tokens == 300
        assert config.temperature == 0.0
        assert config.num_expansions == 3
        assert config.min_rerank_score == 0.25
        assert config.reorder_strategy == "best_first_last"

    def test_custom_config(self):
        """Test custom configuration."""
        config = QueryEnhancementConfig(
            enabled=False,
            model="gpt-4o",
            num_expansions=5,
            min_rerank_score=0.3,
        )

        assert config.enabled is False
        assert config.model == "gpt-4o"
        assert config.num_expansions == 5
        assert config.min_rerank_score == 0.3
