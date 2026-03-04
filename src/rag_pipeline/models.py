"""
CAG RAG Pipeline - Data Models
===============================

Data classes for the RAG pipeline.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


# =============================================================================
# CHUNK MODELS
# =============================================================================


@dataclass
class RetrievedChunk:
    """A retrieved chunk with all metadata."""

    chunk_id: str
    content: str
    score: float

    # Parent reference
    parent_chunk_id: Optional[str] = None

    # Location metadata
    hierarchy: Dict[str, str] = field(default_factory=dict)
    report_id: str = ""
    report_year: Optional[int] = None
    page_physical: int = 0
    page_logical: str = ""
    content_type: str = "paragraph"

    # Semantic enrichment
    finding_type: Optional[str] = None
    severity: Optional[str] = None
    total_amount_crore: Optional[float] = None
    entities_mentioned: List[str] = field(default_factory=list)

    # Recommendation fields
    is_recommendation: bool = False
    recommendation_target: Optional[str] = None
    action_required: Optional[str] = None

    # Section type
    section_type: Optional[str] = None

    # Neighbor chunks (populated during retrieval)
    previous_chunk: Optional["RetrievedChunk"] = None
    next_chunk: Optional["RetrievedChunk"] = None

    def has_semantic_data(self) -> bool:
        """Check if chunk has semantic enrichment data."""
        return bool(
            self.finding_type
            or self.severity
            or self.total_amount_crore
            or self.is_recommendation
        )

    def get_semantic_tags(self) -> List[str]:
        """Get list of semantic tags for display."""
        tags = []

        if self.finding_type:
            tags.append(f"Finding: {self.finding_type.replace('_', ' ').title()}")

        if self.severity:
            tags.append(f"Severity: {self.severity.upper()}")

        if self.total_amount_crore and self.total_amount_crore > 0:
            tags.append(f"Amount: ₹{self.total_amount_crore:.2f} crore")

        if self.is_recommendation:
            tags.append("Recommendation")
            if self.recommendation_target:
                tags.append(f"To: {self.recommendation_target}")

        if self.section_type:
            tags.append(f"Section: {self.section_type.replace('_', ' ').title()}")

        return tags


@dataclass
class ParentContext:
    """Parent chunk context information."""

    chunk_id: str
    toc_entry: str
    hierarchy: Dict[str, str]
    page_range: Tuple[int, int]
    children: List[RetrievedChunk] = field(default_factory=list)

    def get_hierarchy_path(self) -> str:
        """Get formatted hierarchy path."""
        if self.hierarchy:
            return " > ".join(self.hierarchy.values())
        return self.toc_entry


# =============================================================================
# RETRIEVAL RESULT
# =============================================================================


@dataclass
class RetrievalResult:
    """Complete retrieval result."""

    query: str
    total_candidates: int
    total_after_rerank: int
    parents: List[ParentContext]
    filters_applied: Dict[str, Any]
    reranker_used: str
    search_type: str  # "hybrid" or "dense"

    def get_all_chunks(self) -> List[RetrievedChunk]:
        """Get flat list of all retrieved chunks."""
        chunks = []
        for parent in self.parents:
            chunks.extend(parent.children)
        return chunks

    def to_context_string(
        self,
        include_neighbors: bool = True,
        include_semantic_tags: bool = True,
    ) -> str:
        """
        Format retrieval results as context string for LLM.

        Args:
            include_neighbors: Include previous/next chunk snippets
            include_semantic_tags: Include finding_type, severity, etc.

        Returns:
            Formatted context string
        """
        sections = []

        for parent in self.parents:
            # Section header
            hierarchy_path = parent.get_hierarchy_path()
            header = f"## {hierarchy_path}"

            page_start = parent.page_range[0] + 1
            page_end = parent.page_range[1] + 1
            page_info = f"(Pages {page_start}-{page_end})"

            # Format children
            chunks_text = []
            for i, child in enumerate(parent.children, 1):
                parts = []

                # Previous chunk context
                if include_neighbors and child.previous_chunk:
                    prev_snippet = child.previous_chunk.content[-200:]
                    parts.append(f"[...preceding]: {prev_snippet}")

                # Build citation key (must match build_citations() in rag_service.py)
                citation_key = f"{parent.toc_entry}, p.{child.page_physical + 1}"

                # Add source label for LLM to copy
                parts.append(f"[Source: {citation_key}]")

                # Main chunk with relevance indicator
                if child.score > 0.85:
                    relevance = "★★★"
                elif child.score > 0.7:
                    relevance = "★★"
                else:
                    relevance = "★"

                parts.append(f"[{i}]{relevance} {child.content}")

                # Semantic tags
                if include_semantic_tags and child.has_semantic_data():
                    tags = child.get_semantic_tags()
                    parts.append(f"  📋 {' | '.join(tags)}")

                # Next chunk context
                if include_neighbors and child.next_chunk:
                    next_snippet = child.next_chunk.content[:200]
                    parts.append(f"[following...]: {next_snippet}")

                chunks_text.append("\n".join(parts))

            section = f"{header} {page_info}\n\n" + "\n\n".join(chunks_text)
            sections.append(section)

        return "\n\n---\n\n".join(sections)

    def to_citations(self) -> List[Dict[str, Any]]:
        """Generate citation list for the response."""
        citations = []
        num = 1

        for parent in self.parents:
            for child in parent.children:
                citations.append(
                    {
                        "id": num,
                        "report_id": child.report_id,
                        "report_year": child.report_year,
                        "section": parent.toc_entry,
                        "hierarchy": parent.get_hierarchy_path(),
                        "page": child.page_physical + 1,
                        "score": round(child.score, 3),
                        "finding_type": child.finding_type,
                        "severity": child.severity,
                        "amount_crore": child.total_amount_crore,
                    }
                )
                num += 1

        return citations


# =============================================================================
# RAG RESPONSE
# =============================================================================


@dataclass
class Citation:
    """A single citation with full report metadata."""

    id: int
    report_id: str
    section: str
    page: int
    score: float
    finding_type: Optional[str] = None
    severity: Optional[str] = None
    amount_crore: Optional[float] = None

    # NEW fields:
    report_title: str = ""
    filename: str = ""
    audit_year: str = ""  # e.g., "2023-24"

    def format(self) -> str:
        """Format citation for display."""
        base = f"[{self.id}] {self.report_id} - {self.section} (p.{self.page})"

        details = []
        if self.finding_type:
            details.append(self.finding_type.replace("_", " "))
        if self.severity:
            details.append(self.severity)
        if self.amount_crore and self.amount_crore > 0:
            details.append(f"₹{self.amount_crore:.2f}cr")

        if details:
            base += f" [{', '.join(details)}]"

        return base


@dataclass
class RAGResponse:
    """Complete RAG response with answer and metadata."""

    query: str
    answer: str
    citations: List[Citation]

    # Retrieval metadata
    sources_used: int
    context_length: int
    reranker_used: str
    search_type: str

    # LLM metadata
    model_used: str

    def format_with_citations(self) -> str:
        """Format answer with citations at the bottom."""
        formatted = self.answer

        if self.citations:
            formatted += "\n\n---\n**Sources:**\n"
            for cite in self.citations:
                formatted += cite.format() + "\n"

        return formatted

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "query": self.query,
            "answer": self.answer,
            "citations": [
                {
                    "id": c.id,
                    "report_id": c.report_id,
                    "section": c.section,
                    "page": c.page,
                    "score": c.score,
                    "finding_type": c.finding_type,
                    "severity": c.severity,
                    "amount_crore": c.amount_crore,
                }
                for c in self.citations
            ],
            "metadata": {
                "sources_used": self.sources_used,
                "context_length": self.context_length,
                "reranker_used": self.reranker_used,
                "search_type": self.search_type,
                "model_used": self.model_used,
            },
        }
