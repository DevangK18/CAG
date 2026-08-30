"""
Corrective RAG for CAG RAG Pipeline (SOTA Feature 4).

Detects and fixes retrieval/generation failures:
1. RelevanceChecker - Checks if retrieved docs are relevant
2. QueryReformulator - Reformulates failing queries
3. CitationValidator - Validates citations in generated answers

This improves answer quality by detecting and correcting retrieval failures.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from ..core.config import CorrectiveRAGConfig
    from .models import RetrievalResult, RetrievedChunk, ParentContext
except ImportError:
    from src.core.config import CorrectiveRAGConfig
    from models import RetrievalResult, RetrievedChunk, ParentContext

logger = logging.getLogger(__name__)


# =============================================================================
# RELEVANCE CHECKER
# =============================================================================


@dataclass
class RelevanceAssessment:
    """Result of relevance check on retrieved documents."""

    is_sufficient: bool
    overall_score: float
    relevant_count: int
    total_count: int
    weak_chunks: List[str]  # chunk_ids with low relevance
    suggestion: str  # "sufficient", "reformulate", "expand_search"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_sufficient": self.is_sufficient,
            "overall_score": self.overall_score,
            "relevant_count": self.relevant_count,
            "total_count": self.total_count,
            "weak_chunks_count": len(self.weak_chunks),
            "suggestion": self.suggestion,
        }


class RelevanceChecker:
    """
    Checks if retrieved context is relevant to the query.

    Uses reranker scores as a proxy for relevance.
    If too few chunks are relevant, suggests reformulation or expansion.
    """

    def __init__(self, config: CorrectiveRAGConfig):
        self.config = config
        self.min_score = config.min_relevance_score
        self.min_relevant = config.min_relevant_chunks

    def check(
        self,
        query: str,
        retrieval_result: RetrievalResult,
    ) -> RelevanceAssessment:
        """
        Check if retrieved context is sufficient.

        Args:
            query: User's question
            retrieval_result: Retrieved chunks with scores

        Returns:
            RelevanceAssessment with sufficiency analysis
        """
        # Collect all chunks with scores
        all_chunks = []
        for parent in retrieval_result.parents:
            for child in parent.children:
                all_chunks.append(child)

        if not all_chunks:
            return RelevanceAssessment(
                is_sufficient=False,
                overall_score=0.0,
                relevant_count=0,
                total_count=0,
                weak_chunks=[],
                suggestion="reformulate",
            )

        # Count relevant chunks (above threshold)
        relevant_chunks = [c for c in all_chunks if c.score >= self.min_score]
        weak_chunks = [c.chunk_id for c in all_chunks if c.score < self.min_score]

        relevant_count = len(relevant_chunks)
        total_count = len(all_chunks)
        top_score = max(c.score for c in all_chunks)
        avg_score = sum(c.score for c in all_chunks) / total_count

        # Determine if sufficient
        if relevant_count >= self.min_relevant and top_score >= 0.5:
            return RelevanceAssessment(
                is_sufficient=True,
                overall_score=avg_score,
                relevant_count=relevant_count,
                total_count=total_count,
                weak_chunks=weak_chunks,
                suggestion="sufficient",
            )

        # Not enough relevant chunks
        if relevant_count < 2:
            # Very poor retrieval - suggest reformulation
            return RelevanceAssessment(
                is_sufficient=False,
                overall_score=avg_score,
                relevant_count=relevant_count,
                total_count=total_count,
                weak_chunks=weak_chunks,
                suggestion="reformulate",
            )

        # Some relevant chunks but not enough - suggest expansion
        return RelevanceAssessment(
            is_sufficient=False,
            overall_score=avg_score,
            relevant_count=relevant_count,
            total_count=total_count,
            weak_chunks=weak_chunks,
            suggestion="expand_search",
        )


# =============================================================================
# QUERY REFORMULATOR
# =============================================================================


REFORMULATION_PROMPT = """You are helping improve a search query for CAG (Comptroller and Auditor General) audit reports.

The original query did not retrieve relevant documents. Generate an alternative query that might find better results.

Focus on:
1. Using synonyms and alternative phrasings
2. Adding domain-specific terminology (audit, compliance, revenue, expenditure)
3. Broadening narrow terms or narrowing broad terms
4. Using official CAG terminology

Original query: {query}

Top retrieved results were about:
{context_hints}

Generate ONE alternative query (no explanation, just the query):"""


class QueryReformulator:
    """
    Reformulates queries when initial retrieval fails.

    Uses LLM to generate alternative queries based on:
    - Original query
    - What was retrieved (to avoid similar terms)
    - Domain knowledge of CAG terminology
    """

    def __init__(
        self,
        config: CorrectiveRAGConfig,
        openai_client: Optional[OpenAI] = None,
    ):
        self.config = config
        self.openai = openai_client
        self.model = config.reformulation_model

    def reformulate(
        self,
        original_query: str,
        failed_results: RetrievalResult,
    ) -> str:
        """
        Generate alternative query when initial retrieval fails.

        Args:
            original_query: Original user query
            failed_results: Retrieved results that weren't relevant

        Returns:
            Reformulated query string
        """
        # If no LLM, use rule-based reformulation
        if not self.openai:
            return self._rule_based_reformulation(original_query)

        # Build context hints from failed results
        context_hints = self._build_context_hints(failed_results)

        try:
            prompt = REFORMULATION_PROMPT.format(
                query=original_query,
                context_hints=context_hints,
            )

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.7,  # Some creativity for alternatives
            )

            reformulated = response.choices[0].message.content.strip()
            logger.info(f"Query reformulated: '{original_query}' → '{reformulated}'")
            return reformulated

        except Exception as e:
            logger.warning(f"Query reformulation failed: {e}")
            return self._rule_based_reformulation(original_query)

    def _build_context_hints(self, results: RetrievalResult) -> str:
        """Build context hints from failed retrieval results."""
        hints = []
        for parent in results.parents[:3]:  # Top 3 parents
            for child in parent.children[:1]:  # First child of each
                content_preview = child.content[:100] if child.content else ""
                hints.append(f"- {content_preview}...")

        if not hints:
            return "No relevant results found"

        return "\n".join(hints)

    def _rule_based_reformulation(self, query: str) -> str:
        """Rule-based query reformulation fallback."""
        # Common substitutions for CAG domain
        substitutions = {
            r"money lost": "revenue loss quantified",
            r"wasted money": "infructuous expenditure",
            r"unused funds": "unspent balance",
            r"missing money": "misappropriation",
            r"problems": "audit observations",
            r"issues": "findings",
            r"wrong": "irregularity",
            r"late": "delay in",
            r"toll": "toll collection Electronic Toll Collection",
            r"tax": "revenue duty levy",
        }

        reformulated = query
        for pattern, replacement in substitutions.items():
            if re.search(pattern, query, re.I):
                reformulated = re.sub(pattern, replacement, query, flags=re.I)
                break

        # If no substitution made, add domain qualifier
        if reformulated == query:
            reformulated = f"CAG audit finding: {query}"

        return reformulated


# =============================================================================
# CITATION VALIDATOR
# =============================================================================


@dataclass
class CitationValidation:
    """Result of citation validation."""

    valid_citations: List[str]
    invalid_citations: List[str]
    all_valid: bool
    cleaned_answer: str  # Answer with invalid citations stripped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid_count": len(self.valid_citations),
            "invalid_count": len(self.invalid_citations),
            "all_valid": self.all_valid,
        }


class CitationValidator:
    """
    Validates citations in generated answers.

    Checks that:
    1. Cited sections actually exist in retrieved context
    2. Cited page numbers are within expected ranges
    3. Citation format is correct

    Optionally strips invalid citations from the answer.
    """

    # Citation pattern: [Section Name, p.XX] or [Source: Section Name, p.XX]
    CITATION_PATTERN = re.compile(
        r'\[(?:Source:\s*)?([^\[\]]+?),\s*p\.?\s*(\d+)\]',
        re.IGNORECASE
    )

    def __init__(self, config: CorrectiveRAGConfig):
        self.config = config
        self.strip_invalid = config.strip_invalid_citations

    def validate(
        self,
        answer: str,
        context_chunks: RetrievalResult,
    ) -> CitationValidation:
        """
        Validate and optionally fix citations in generated answer.

        Args:
            answer: Generated answer with citations
            context_chunks: Retrieved context used for generation

        Returns:
            CitationValidation with valid/invalid lists and cleaned answer
        """
        # Extract all citations from answer
        citations = self.CITATION_PATTERN.findall(answer)

        if not citations:
            return CitationValidation(
                valid_citations=[],
                invalid_citations=[],
                all_valid=True,
                cleaned_answer=answer,
            )

        # Build set of valid section references from context
        valid_sections = self._extract_valid_sections(context_chunks)
        valid_pages = self._extract_valid_pages(context_chunks)

        valid_citations = []
        invalid_citations = []

        for section, page in citations:
            page_num = int(page)
            citation_str = f"[{section}, p.{page}]"

            # Check if section exists (fuzzy match)
            section_valid = self._section_exists(section, valid_sections)

            # Check if page is in valid range
            page_valid = page_num in valid_pages or len(valid_pages) == 0

            if section_valid and page_valid:
                valid_citations.append(citation_str)
            else:
                invalid_citations.append(citation_str)
                logger.debug(f"Invalid citation: {citation_str} (section: {section_valid}, page: {page_valid})")

        # Optionally strip invalid citations
        cleaned_answer = answer
        if self.strip_invalid and invalid_citations:
            for invalid in invalid_citations:
                cleaned_answer = cleaned_answer.replace(invalid, "")
            # Clean up extra whitespace
            cleaned_answer = re.sub(r'\s+', ' ', cleaned_answer).strip()
            cleaned_answer = re.sub(r'\s+\.', '.', cleaned_answer)

        return CitationValidation(
            valid_citations=valid_citations,
            invalid_citations=invalid_citations,
            all_valid=len(invalid_citations) == 0,
            cleaned_answer=cleaned_answer,
        )

    def _extract_valid_sections(self, results: RetrievalResult) -> set:
        """Extract valid section names from retrieval context."""
        sections = set()
        for parent in results.parents:
            if parent.toc_entry:
                sections.add(parent.toc_entry.lower())
                # Also add partial matches (without section numbers)
                parts = parent.toc_entry.split()
                if len(parts) > 1:
                    sections.add(' '.join(parts[1:]).lower())
        return sections

    def _extract_valid_pages(self, results: RetrievalResult) -> set:
        """Extract valid page numbers from retrieval context."""
        pages = set()
        for parent in results.parents:
            for child in parent.children:
                if hasattr(child, 'page_physical'):
                    # Add page and surrounding pages (±2)
                    page = child.page_physical + 1  # 0-indexed to 1-indexed
                    for p in range(max(1, page - 2), page + 3):
                        pages.add(p)
        return pages

    def _section_exists(self, cited_section: str, valid_sections: set) -> bool:
        """Check if cited section exists in valid sections (fuzzy match)."""
        cited_lower = cited_section.lower().strip()

        # Exact match
        if cited_lower in valid_sections:
            return True

        # Partial match (cited is substring or vice versa)
        for valid in valid_sections:
            if cited_lower in valid or valid in cited_lower:
                return True

            # Fuzzy word overlap (at least 60% words match)
            cited_words = set(cited_lower.split())
            valid_words = set(valid.split())
            overlap = len(cited_words & valid_words)
            if overlap >= min(len(cited_words), len(valid_words)) * 0.6:
                return True

        return False


# =============================================================================
# CORRECTIVE RAG SERVICE
# =============================================================================


class CorrectiveRAGService:
    """
    Orchestrates corrective RAG flow:
    1. Check relevance of retrieval
    2. If insufficient, reformulate and re-retrieve
    3. After generation, validate citations
    """

    def __init__(
        self,
        config: CorrectiveRAGConfig,
        openai_client: Optional[OpenAI] = None,
    ):
        self.config = config
        self.relevance_checker = RelevanceChecker(config)
        self.reformulator = QueryReformulator(config, openai_client)
        self.citation_validator = CitationValidator(config)

    def check_and_correct_retrieval(
        self,
        query: str,
        retrieval_result: RetrievalResult,
        retrieve_fn,  # Callable to re-retrieve
    ) -> Tuple[RetrievalResult, Dict[str, Any]]:
        """
        Check retrieval quality and correct if needed.

        Args:
            query: Original query
            retrieval_result: Initial retrieval result
            retrieve_fn: Function to call for re-retrieval

        Returns:
            Tuple of (possibly corrected RetrievalResult, correction_info dict)
        """
        correction_info = {
            "original_query": query,
            "reformulations": [],
            "retrieval_attempts": 1,
            "final_assessment": None,
        }

        # Check initial relevance
        assessment = self.relevance_checker.check(query, retrieval_result)
        correction_info["initial_assessment"] = assessment.to_dict()

        if assessment.is_sufficient:
            correction_info["final_assessment"] = assessment.to_dict()
            return retrieval_result, correction_info

        # Not sufficient - try reformulation
        current_query = query
        current_result = retrieval_result

        for attempt in range(self.config.max_reformulations):
            # Reformulate query
            reformulated = self.reformulator.reformulate(current_query, current_result)
            correction_info["reformulations"].append({
                "attempt": attempt + 1,
                "original": current_query,
                "reformulated": reformulated,
            })

            # Re-retrieve
            try:
                new_result = retrieve_fn(reformulated)
                correction_info["retrieval_attempts"] += 1

                # Check new relevance
                new_assessment = self.relevance_checker.check(reformulated, new_result)

                if new_assessment.is_sufficient:
                    correction_info["final_assessment"] = new_assessment.to_dict()
                    logger.info(f"Retrieval corrected after {attempt + 1} reformulation(s)")
                    return new_result, correction_info

                # Update for next iteration
                current_query = reformulated
                current_result = new_result

            except Exception as e:
                logger.warning(f"Reformulation retrieval failed: {e}")
                break

        # Exhausted reformulations - return best result
        final_assessment = self.relevance_checker.check(current_query, current_result)
        correction_info["final_assessment"] = final_assessment.to_dict()

        logger.info(f"Retrieval correction exhausted after {correction_info['retrieval_attempts']} attempts")
        return current_result, correction_info

    def validate_and_clean_answer(
        self,
        answer: str,
        retrieval_result: RetrievalResult,
    ) -> Tuple[str, CitationValidation]:
        """
        Validate citations and clean answer.

        Args:
            answer: Generated answer
            retrieval_result: Context used for generation

        Returns:
            Tuple of (cleaned answer, validation result)
        """
        validation = self.citation_validator.validate(answer, retrieval_result)

        if not validation.all_valid:
            logger.info(
                f"Citation validation: {len(validation.valid_citations)} valid, "
                f"{len(validation.invalid_citations)} invalid"
            )

        return validation.cleaned_answer, validation


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_corrective_service(
    config: CorrectiveRAGConfig = None,
    openai_client: OpenAI = None,
) -> CorrectiveRAGService:
    """Create a CorrectiveRAGService with default or custom config."""
    if config is None:
        config = CorrectiveRAGConfig()
    return CorrectiveRAGService(config, openai_client)


def quick_relevance_check(
    retrieval_result: RetrievalResult,
    min_score: float = 0.25,
) -> bool:
    """Quick check if retrieval is relevant enough."""
    checker = RelevanceChecker(CorrectiveRAGConfig(min_relevance_score=min_score))
    assessment = checker.check("", retrieval_result)
    return assessment.is_sufficient
