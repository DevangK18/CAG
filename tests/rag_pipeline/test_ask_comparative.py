"""
Tests for refactored ask_comparative() (Phase 12 Step 7).

Test cases:
1. Comparative with empty retrievals returns the empty-state response
2. Comparative with mocked retrievals returns merged response with citations
3. Groundedness runs on merged result when service is set
4. Entity-filtering narrows report_ids when query mentions a known entity (mock entity_service)
5. Entity-filtering falls back to original report_ids when no reports match
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from src.rag_pipeline.rag_service import RAGService
from src.rag_pipeline.models import (
    RetrievalResult,
    ParentContext,
    RetrievedChunk,
    RAGResponse,
)
from src.core.config import RAGConfig, LLMProvider


@dataclass
class MockReportInfo:
    """Mock report info for registry."""

    report_id: str
    report_title: str
    audit_year: str
    filename: str
    government_body_type: str = "union"


class TestAskComparativeEmptyRetrievals:
    """Test comparative with empty retrievals returns empty-state response."""

    @patch("src.rag_pipeline.rag_service.get_registry")
    @patch("src.rag_pipeline.rag_service.OpenAI")
    def test_returns_empty_response_when_no_results(self, mock_openai, mock_registry):
        """When retrieval returns 0 results for all reports, return empty-state response."""
        # Setup config
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI

        # Mock registry
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance

        # Setup RAG service
        rag = RAGService(config)

        # Mock retrieval to return empty results
        empty_result = RetrievalResult(
            query="test query",
            total_candidates=0,
            total_after_rerank=0,
            parents=[],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        with patch.object(rag.retrieval, "retrieve", return_value=empty_result):
            response = rag.ask_comparative(
                question="Compare findings across years",
                report_ids=["2022_01_Report", "2023_01_Report"],
                top_k_per_report=5,
            )

        # Verify empty response
        assert response.query == "Compare findings across years"
        assert (
            response.answer == "No relevant information found in the specified reports."
        )
        assert response.citations == []
        assert response.sources_used == 0
        assert response.context_length == 0
        assert response.search_type == "comparative_empty"


class TestAskComparativeMergedResponse:
    """Test comparative with mocked retrievals returns merged response with citations."""

    @patch("src.rag_pipeline.rag_service.get_registry")
    @patch("src.rag_pipeline.rag_service.OpenAI")
    def test_merges_per_report_retrievals(self, mock_openai, mock_registry):
        """Retrieval results from multiple reports are merged correctly."""
        # Setup config
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI

        # Mock OpenAI client
        mock_client = Mock()
        mock_openai.return_value = mock_client

        # Mock LLM response
        mock_completion = Mock()
        mock_completion.choices = [Mock(message=Mock(content="Merged answer here"))]
        mock_client.chat.completions.create.return_value = mock_completion

        # Mock registry
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        mock_registry_instance.get_report.side_effect = [
            MockReportInfo(
                report_id="2022_01_Report",
                report_title="Report 2022",
                audit_year="2022-23",
                filename="report_2022.pdf",
            ),
            MockReportInfo(
                report_id="2023_01_Report",
                report_title="Report 2023",
                audit_year="2023-24",
                filename="report_2023.pdf",
            ),
        ]

        # Setup RAG service
        rag = RAGService(config)

        # Mock retrieval results for each report
        result_2022 = RetrievalResult(
            query="test query",
            total_candidates=10,
            total_after_rerank=3,
            parents=[
                ParentContext(
                    chunk_id="parent_2022_1",
                    toc_entry="Section 1",
                    hierarchy={"h1": "Executive Summary"},
                    page_range=(10, 12),
                    children=[
                        RetrievedChunk(
                            chunk_id="child_2022_1",
                            content="Finding from 2022",
                            score=0.95,
                            report_id="2022_01_Report",
                            page_physical=10,
                            report_year="2022-23",
                        )
                    ],
                )
            ],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        result_2023 = RetrievalResult(
            query="test query",
            total_candidates=12,
            total_after_rerank=4,
            parents=[
                ParentContext(
                    chunk_id="parent_2023_1",
                    toc_entry="Section 2",
                    hierarchy={"h1": "Key Findings"},
                    page_range=(15, 18),
                    children=[
                        RetrievedChunk(
                            chunk_id="child_2023_1",
                            content="Finding from 2023",
                            score=0.90,
                            report_id="2023_01_Report",
                            page_physical=15,
                            report_year="2023-24",
                        )
                    ],
                )
            ],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        # Mock retrieval to return different results based on report_id filter
        def mock_retrieve(query, top_k, filters, enhancement=None):
            if filters.get("report_id") == "2022_01_Report":
                return result_2022
            elif filters.get("report_id") == "2023_01_Report":
                return result_2023
            return RetrievalResult(
                query=query,
                total_candidates=0,
                total_after_rerank=0,
                parents=[],
                filters_applied=filters,
                reranker_used="none",
                search_type="hybrid",
            )

        with patch.object(rag.retrieval, "retrieve", side_effect=mock_retrieve):
            response = rag.ask_comparative(
                question="Compare findings",
                report_ids=["2022_01_Report", "2023_01_Report"],
                top_k_per_report=5,
            )

        # Verify merged response
        assert response.query == "Compare findings"
        assert response.answer == "Merged answer here"
        assert response.sources_used == 2  # merged total
        assert len(response.citations) == 2  # one from each report
        assert response.search_type == "comparative"

        # Verify citations have correct metadata
        citation_report_ids = {c.report_id for c in response.citations}
        assert citation_report_ids == {"2022_01_Report", "2023_01_Report"}


class TestAskComparativeGroundedness:
    """Test groundedness runs on merged result when service is set."""

    @patch("src.rag_pipeline.rag_service.get_registry")
    @patch("src.rag_pipeline.rag_service.OpenAI")
    def test_runs_groundedness_verification(self, mock_openai, mock_registry):
        """When groundedness_service is enabled, it verifies the merged result."""
        # Setup config with groundedness enabled
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI
        config.groundedness.enabled = True

        # Mock OpenAI client
        mock_client = Mock()
        mock_openai.return_value = mock_client

        # Mock LLM response
        mock_completion = Mock()
        mock_completion.choices = [Mock(message=Mock(content="Answer with claims"))]
        mock_client.chat.completions.create.return_value = mock_completion

        # Mock registry
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        mock_registry_instance.get_report.return_value = MockReportInfo(
            report_id="2022_01_Report",
            report_title="Report 2022",
            audit_year="2022-23",
            filename="report_2022.pdf",
        )

        # Setup RAG service
        rag = RAGService(config)

        # Mock groundedness service
        mock_groundedness_report = Mock()
        mock_groundedness_report.verified = True
        mock_groundedness_report.num_grounded = 3
        mock_groundedness_report.num_claims = 3
        mock_groundedness_report.to_dict.return_value = {
            "verified": True,
            "num_grounded": 3,
            "num_claims": 3,
        }

        rag.groundedness_service = Mock()
        rag.groundedness_service.verify.return_value = mock_groundedness_report

        # Mock retrieval
        result = RetrievalResult(
            query="test query",
            total_candidates=10,
            total_after_rerank=2,
            parents=[
                ParentContext(
                    chunk_id="parent_1",
                    toc_entry="Section 1",
                    hierarchy={"h1": "Test Section"},
                    page_range=(10, 12),
                    children=[
                        RetrievedChunk(
                            chunk_id="child_1",
                            content="Finding",
                            score=0.95,
                            report_id="2022_01_Report",
                            page_physical=10,
                            report_year="2022-23",
                        )
                    ],
                )
            ],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        with patch.object(rag.retrieval, "retrieve", return_value=result):
            response = rag.ask_comparative(
                question="Test query",
                report_ids=["2022_01_Report"],
                top_k_per_report=5,
            )

        # Verify groundedness was called
        assert rag.groundedness_service.verify.called
        verify_call_args = rag.groundedness_service.verify.call_args

        # First arg should be the answer
        assert verify_call_args[0][0] == "Answer with claims"

        # Second arg should be a RetrievalResult
        assert isinstance(verify_call_args[0][1], RetrievalResult)

        # Verify groundedness dict is in response
        assert response.groundedness is not None
        assert response.groundedness["verified"] is True


class TestAskComparativeEntityFiltering:
    """Test entity-filtering narrows report_ids when query mentions a known entity."""

    @patch("src.rag_pipeline.rag_service.get_registry")
    @patch("src.rag_pipeline.rag_service.OpenAI")
    @patch("src.entity_graph.entity_service.get_entity_service")
    def test_narrows_reports_via_entity_graph(
        self, mock_get_entity_service, mock_openai, mock_registry
    ):
        """When entity_graph is enabled and query mentions a known entity, reports are narrowed."""
        # Setup config with entity_graph enabled
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI

        # Enable entity graph
        from src.core.config import EntityGraphConfig

        config.entity_graph = EntityGraphConfig()
        config.entity_graph.enabled = True
        config.entity_graph.enable_comparative_filtering = True

        # Mock OpenAI client
        mock_client = Mock()
        mock_openai.return_value = mock_client
        mock_completion = Mock()
        mock_completion.choices = [Mock(message=Mock(content="Filtered answer"))]
        mock_client.chat.completions.create.return_value = mock_completion

        # Mock registry
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        mock_registry_instance.get_report.return_value = MockReportInfo(
            report_id="2023_01_Report",
            report_title="Report 2023",
            audit_year="2023-24",
            filename="report_2023.pdf",
        )

        # Mock entity service
        mock_entity_service = Mock()
        mock_get_entity_service.return_value = mock_entity_service

        # Mock extract_entities_from_query to return NHAI
        mock_entity_service.extract_entities_from_query.return_value = [
            {"id": 1, "canonical_name": "NHAI"}
        ]

        # Mock get_reports_for_entity to return subset of reports
        mock_entity_service.get_reports_for_entity.return_value = [
            "2022_01_Report",
            "2023_01_Report",
        ]

        # Setup RAG service
        rag = RAGService(config)

        # Mock retrieval
        result = RetrievalResult(
            query="test query",
            total_candidates=10,
            total_after_rerank=2,
            parents=[
                ParentContext(
                    chunk_id="parent_1",
                    toc_entry="Section 1",
                    hierarchy={"h1": "Test Section"},
                    page_range=(10, 12),
                    children=[
                        RetrievedChunk(
                            chunk_id="child_1",
                            content="Finding",
                            score=0.95,
                            report_id="2023_01_Report",
                            page_physical=10,
                            report_year="2023-24",
                        )
                    ],
                )
            ],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        with patch.object(rag.retrieval, "retrieve", return_value=result):
            response = rag.ask_comparative(
                question="What are NHAI findings?",
                report_ids=["2022_01_Report", "2023_01_Report", "2024_01_Report"],
                top_k_per_report=5,
            )

        # Verify entity filtering was applied
        assert response.agentic_trace is not None
        assert response.agentic_trace["entity_filter_applied"] is True
        assert response.agentic_trace["narrowed_from"] == 3
        assert response.agentic_trace["narrowed_to"] == 2  # only reports mentioning NHAI

    @patch("src.rag_pipeline.rag_service.get_registry")
    @patch("src.rag_pipeline.rag_service.OpenAI")
    @patch("src.entity_graph.entity_service.get_entity_service")
    def test_falls_back_when_no_entity_reports_match(
        self, mock_get_entity_service, mock_openai, mock_registry
    ):
        """When entity is recognized but no reports in series mention it, fall back to original report_ids."""
        # Setup config with entity_graph enabled
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI

        from src.core.config import EntityGraphConfig

        config.entity_graph = EntityGraphConfig()
        config.entity_graph.enabled = True
        config.entity_graph.enable_comparative_filtering = True

        # Mock OpenAI client
        mock_client = Mock()
        mock_openai.return_value = mock_client
        mock_completion = Mock()
        mock_completion.choices = [Mock(message=Mock(content="Fallback answer"))]
        mock_client.chat.completions.create.return_value = mock_completion

        # Mock registry
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        mock_registry_instance.get_report.return_value = MockReportInfo(
            report_id="2022_01_Report",
            report_title="Report 2022",
            audit_year="2022-23",
            filename="report_2022.pdf",
        )

        # Mock entity service
        mock_entity_service = Mock()
        mock_get_entity_service.return_value = mock_entity_service

        # Mock extract_entities_from_query to return an entity
        mock_entity_service.extract_entities_from_query.return_value = [
            {"id": 5, "canonical_name": "Unknown PSU"}
        ]

        # Mock get_reports_for_entity to return reports NOT in the series
        mock_entity_service.get_reports_for_entity.return_value = [
            "2020_01_Report",
            "2021_01_Report",
        ]  # Different reports

        # Setup RAG service
        rag = RAGService(config)

        # Mock retrieval
        result = RetrievalResult(
            query="test query",
            total_candidates=10,
            total_after_rerank=2,
            parents=[
                ParentContext(
                    chunk_id="parent_1",
                    toc_entry="Section 1",
                    hierarchy={"h1": "Test Section"},
                    page_range=(10, 12),
                    children=[
                        RetrievedChunk(
                            chunk_id="child_1",
                            content="Finding",
                            score=0.95,
                            report_id="2022_01_Report",
                            page_physical=10,
                            report_year="2022-23",
                        )
                    ],
                )
            ],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        retrieval_calls = []

        def capture_retrieve(query, top_k, filters, enhancement=None):
            retrieval_calls.append(filters.get("report_id"))
            return result

        with patch.object(rag.retrieval, "retrieve", side_effect=capture_retrieve):
            response = rag.ask_comparative(
                question="What are Unknown PSU findings?",
                report_ids=["2022_01_Report", "2023_01_Report"],
                top_k_per_report=5,
            )

        # Verify all original report_ids were used (no narrowing)
        assert set(retrieval_calls) == {"2022_01_Report", "2023_01_Report"}

        # No entity_filter_applied in trace (or it's False/None)
        if response.agentic_trace:
            assert response.agentic_trace.get("entity_filter_applied") is not True


class TestAskComparativeBackwardCompatibility:
    """Test that ask_comparative works when entity_graph is not configured."""

    @patch("src.rag_pipeline.rag_service.get_registry")
    @patch("src.rag_pipeline.rag_service.OpenAI")
    def test_works_without_entity_graph_config(self, mock_openai, mock_registry):
        """ask_comparative works correctly when entity_graph is not in config (backward compat)."""
        # Setup config WITHOUT entity_graph
        config = RAGConfig()
        config.llm.provider = LLMProvider.OPENAI

        # Mock OpenAI client
        mock_client = Mock()
        mock_openai.return_value = mock_client
        mock_completion = Mock()
        mock_completion.choices = [Mock(message=Mock(content="Answer without entity graph"))]
        mock_client.chat.completions.create.return_value = mock_completion

        # Mock registry
        mock_registry_instance = Mock()
        mock_registry.return_value = mock_registry_instance
        mock_registry_instance.get_report.return_value = MockReportInfo(
            report_id="2022_01_Report",
            report_title="Report 2022",
            audit_year="2022-23",
            filename="report_2022.pdf",
        )

        # Setup RAG service
        rag = RAGService(config)

        # Verify entity_graph is not configured
        assert not hasattr(config, "entity_graph") or not config.entity_graph.enabled

        # Mock retrieval
        result = RetrievalResult(
            query="test query",
            total_candidates=10,
            total_after_rerank=2,
            parents=[
                ParentContext(
                    chunk_id="parent_1",
                    toc_entry="Section 1",
                    hierarchy={"h1": "Test Section"},
                    page_range=(10, 12),
                    children=[
                        RetrievedChunk(
                            chunk_id="child_1",
                            content="Finding",
                            score=0.95,
                            report_id="2022_01_Report",
                            page_physical=10,
                            report_year="2022-23",
                        )
                    ],
                )
            ],
            filters_applied={},
            reranker_used="cohere",
            search_type="hybrid",
        )

        with patch.object(rag.retrieval, "retrieve", return_value=result):
            # Should not raise any AttributeError
            response = rag.ask_comparative(
                question="Test query",
                report_ids=["2022_01_Report"],
                top_k_per_report=5,
            )

        # Verify response works normally
        assert response.query == "Test query"
        assert response.answer == "Answer without entity graph"
        assert response.agentic_trace is None  # No entity filtering
