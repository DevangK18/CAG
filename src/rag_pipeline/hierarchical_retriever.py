"""
RAPTOR-style Hierarchical Retriever for CAG RAG Pipeline.

Retrieves from pre-computed hierarchical summaries:
- Level 3: Report-level summaries
- Level 2: Chapter-level summaries
- Level 1: Section-level summaries
- Level 0: Original chunks (fallback)

This enables fast answers for high-level queries without scanning
hundreds of chunks.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from pathlib import Path

try:
    from ..core.config import RAGConfig, HierarchicalConfig
    from .models import RetrievalResult, RetrievedChunk, ParentContext
    from .qdrant_service import QdrantService
    from .embedding_service import EmbeddingService
except ImportError:
    from src.core.config import RAGConfig, HierarchicalConfig
    from models import RetrievalResult, RetrievedChunk, ParentContext
    from qdrant_service import QdrantService
    from embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass
class HierarchicalChunk:
    """A chunk from the hierarchical summary tree."""

    chunk_id: str
    content: str  # The summary text
    hierarchy_level: int  # 1=section, 2=chapter, 3=report
    parent_chunk_id: str  # Links to original parent chunk
    title: str
    report_id: str
    score: float = 0.0


class HierarchicalRetriever:
    """
    RAPTOR-style hierarchical retrieval using pre-computed summaries.

    Supports drill-down: if top results at a level are not relevant enough,
    automatically drills down to more specific levels.
    """

    def __init__(
        self,
        qdrant_service: QdrantService,
        embedding_service: EmbeddingService,
        config: RAGConfig,
    ):
        self.qdrant = qdrant_service
        self.embedding = embedding_service
        self.config = config
        self.hierarchical_config = config.hierarchical

    def retrieve(
        self,
        query: str,
        level: Optional[int] = None,
        report_id: Optional[str] = None,
        top_k: int = 5,
        enable_drill_down: bool = True,
    ) -> RetrievalResult:
        """
        Retrieve from hierarchical summaries.

        Args:
            query: User question
            level: Hierarchy level to search (1=section, 2=chapter, 3=report).
                   If None, uses config default (typically 2 for chapter).
            report_id: Optional filter to specific report
            top_k: Number of summaries to retrieve
            enable_drill_down: If True, drills down when relevance is low

        Returns:
            RetrievalResult with hierarchical summaries as chunks
        """
        if level is None:
            level = self.hierarchical_config.default_level

        logger.info(f"Hierarchical retrieval at L{level}: '{query[:50]}...'")

        # Build filter for hierarchy level
        filters = self._build_filters(level, report_id)

        # Search at specified level
        results = self.qdrant.search_with_filter(
            query=query,
            filter_conditions=filters,
            top_k=top_k,
        )

        if not results:
            logger.info(f"No results at L{level}, trying standard retrieval")
            return self._fallback_to_standard(query, report_id, top_k)

        # Check if top result is relevant enough
        top_score = results[0].score if results else 0.0

        if (
            enable_drill_down
            and top_score < self.hierarchical_config.drill_down_threshold
            and level > 1
        ):
            logger.info(
                f"Top score {top_score:.3f} below threshold "
                f"{self.hierarchical_config.drill_down_threshold}, drilling down to L{level-1}"
            )
            return self.retrieve(
                query=query,
                level=level - 1,
                report_id=report_id,
                top_k=top_k,
                enable_drill_down=True,
            )

        # At L1 or good relevance - return results
        return self._build_retrieval_result(results, query, level)

    def retrieve_for_overview(
        self,
        query: str,
        report_id: Optional[str] = None,
        top_k: int = 3,
    ) -> RetrievalResult:
        """
        Retrieve chapter-level summaries for overview queries.

        This is optimized for queries like:
        - "Summarize the main themes"
        - "What are the key findings?"
        - "Give me an overview"

        Returns chapter-level (L2) summaries without drill-down.
        """
        return self.retrieve(
            query=query,
            level=2,  # Chapter level
            report_id=report_id,
            top_k=top_k,
            enable_drill_down=False,  # Don't drill down for overview
        )

    def retrieve_section_summaries(
        self,
        query: str,
        report_id: Optional[str] = None,
        top_k: int = 8,
    ) -> RetrievalResult:
        """
        Retrieve section-level summaries for detailed queries.

        This is optimized for queries that need section-level detail
        but not full chunk content.
        """
        return self.retrieve(
            query=query,
            level=1,  # Section level
            report_id=report_id,
            top_k=top_k,
            enable_drill_down=False,
        )

    def _build_filters(
        self,
        level: int,
        report_id: Optional[str],
    ) -> Dict[str, Any]:
        """Build Qdrant filter conditions for hierarchical search."""
        conditions = []

        # Filter by hierarchy level
        conditions.append({
            "key": "hierarchy_level",
            "match": {"value": level}
        })

        # Filter by content type (hierarchical summaries)
        conditions.append({
            "key": "content_type",
            "match": {"any": ["chapter_summary", "section_summary"]}
        })

        # Optional report filter
        if report_id:
            conditions.append({
                "key": "report_id",
                "match": {"value": report_id}
            })

        return {"must": conditions}

    def _build_retrieval_result(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        level: int,
    ) -> RetrievalResult:
        """Convert hierarchical chunks to RetrievalResult format."""
        # Group by parent for consistent structure
        parents = []

        for chunk in chunks:
            # Create a ParentContext wrapping the hierarchical chunk
            parent = ParentContext(
                chunk_id=chunk.chunk_id,
                toc_entry=getattr(chunk, 'title', chunk.chunk_id),
                hierarchy={
                    f"level_{level}": getattr(chunk, 'title', ''),
                    "hierarchy_level": level,
                },
                page_range=(0, 0),  # Summaries don't have page ranges
                children=[chunk],
            )
            parents.append(parent)

        return RetrievalResult(
            query=query,
            total_candidates=len(chunks),
            total_after_rerank=len(chunks),
            parents=parents,
            filters_applied={"hierarchy_level": level},
            reranker_used="none",  # Hierarchical doesn't use reranker
            search_type=f"hierarchical_L{level}",
        )

    def _fallback_to_standard(
        self,
        query: str,
        report_id: Optional[str],
        top_k: int,
    ) -> RetrievalResult:
        """Fall back to standard chunk retrieval when hierarchical fails."""
        logger.info("Falling back to standard retrieval")

        # This would call the standard retrieval service
        # For now, return empty result - the caller should handle this
        return RetrievalResult(
            query=query,
            total_candidates=0,
            total_after_rerank=0,
            parents=[],
            filters_applied={},
            reranker_used="none",
            search_type="hierarchical_fallback",
        )


# =============================================================================
# HIERARCHICAL INDEXER
# =============================================================================


class HierarchicalIndexer:
    """
    Indexes RAPTOR hierarchical summaries into Qdrant.

    Summaries are stored in the same collection as child chunks but with
    special content_type and hierarchy_level metadata.
    """

    def __init__(
        self,
        qdrant_service: QdrantService,
        embedding_service: EmbeddingService,
        config: RAGConfig,
    ):
        self.qdrant = qdrant_service
        self.embedding = embedding_service
        self.config = config

    def index_hierarchical_summaries(
        self,
        hierarchical_path: Path,
        report_id: str,
    ) -> int:
        """
        Index RAPTOR hierarchical summaries into Qdrant.

        Args:
            hierarchical_path: Path to {report_id}_hierarchical.json
            report_id: The report ID

        Returns:
            Number of summaries indexed
        """
        import json
        import uuid

        with open(hierarchical_path) as f:
            data = json.load(f)

        points = []

        # Index chapter summaries (L2)
        for chapter in data.get("chapter_summaries", []):
            if not chapter.get("summary"):
                continue

            chunk_id = f"{report_id}_L2_{chapter['parent_chunk_id']}"
            embedding = self.embedding.embed_query(chapter["summary"])

            points.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)),
                "vector": embedding,
                "payload": {
                    "chunk_id": chunk_id,
                    "content": chapter["summary"],
                    "content_type": "chapter_summary",
                    "hierarchy_level": 2,
                    "parent_chunk_id": chapter["parent_chunk_id"],
                    "title": chapter["title"],
                    "report_id": report_id,
                    "tier": chapter.get("tier", "union"),
                },
            })

        # Index section summaries (L1)
        for section in data.get("section_summaries", []):
            if not section.get("summary"):
                continue

            chunk_id = f"{report_id}_L1_{section['parent_chunk_id']}"
            embedding = self.embedding.embed_query(section["summary"])

            points.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)),
                "vector": embedding,
                "payload": {
                    "chunk_id": chunk_id,
                    "content": section["summary"],
                    "content_type": "section_summary",
                    "hierarchy_level": 1,
                    "parent_chunk_id": section["parent_chunk_id"],
                    "title": section["title"],
                    "report_id": report_id,
                    "tier": section.get("tier", "union"),
                },
            })

        if not points:
            logger.warning(f"No hierarchical summaries to index for {report_id}")
            return 0

        # Upsert to Qdrant
        self.qdrant.upsert_points(
            collection_name=self.config.qdrant.child_collection,
            points=points,
        )

        logger.info(f"Indexed {len(points)} hierarchical summaries for {report_id}")
        return len(points)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def is_overview_query(query: str) -> bool:
    """
    Check if a query is asking for an overview/summary.

    These queries benefit from hierarchical retrieval at chapter level.
    """
    overview_patterns = [
        "summarize",
        "summary",
        "overview",
        "main themes",
        "key findings",
        "main findings",
        "what are the",
        "major issues",
        "key issues",
        "give me an overview",
        "tell me about",
        "what does the report say",
        "high-level",
        "briefly describe",
        "in brief",
    ]

    query_lower = query.lower()
    return any(pattern in query_lower for pattern in overview_patterns)


def get_recommended_level(query: str) -> int:
    """
    Recommend hierarchy level based on query type.

    Returns:
        3 for report-level queries
        2 for chapter-level queries (default)
        1 for section-level queries
        0 for detailed queries (use standard retrieval)
    """
    query_lower = query.lower()

    # Report-level (L3)
    if any(p in query_lower for p in [
        "entire report",
        "whole report",
        "overall summary",
        "report summary",
    ]):
        return 3

    # Section-level (L1)
    if any(p in query_lower for p in [
        "specific section",
        "in section",
        "paragraph",
        "detailed",
        "specific finding",
    ]):
        return 1

    # Standard retrieval (L0)
    if any(p in query_lower for p in [
        "exact quote",
        "verbatim",
        "specific amount",
        "₹",
        "crore",
        "lakh",
    ]):
        return 0

    # Default: chapter level (L2)
    return 2
