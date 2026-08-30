"""
Self-RAG Retrieval Decider for CAG RAG Pipeline (SOTA Feature 3).

Decides whether retrieval is needed for a given query:
- SKIP: Answer from parametric knowledge (definitional queries)
- RETRIEVE: Standard retrieval needed
- MULTI_RETRIEVE: Multiple retrieval rounds (complex queries)

This improves efficiency by skipping unnecessary retrieval for
queries that can be answered from model knowledge.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

try:
    from ..core.config import SelfRAGConfig
except ImportError:
    from src.core.config import SelfRAGConfig

logger = logging.getLogger(__name__)


class RetrievalDecision(Enum):
    """Retrieval decision types."""

    SKIP = "skip"            # Answer from parametric knowledge
    RETRIEVE = "retrieve"     # Standard retrieval
    MULTI_RETRIEVE = "multi"  # Multiple retrieval rounds


@dataclass
class DecisionResult:
    """Result of retrieval decision."""

    decision: RetrievalDecision
    confidence: float
    reasoning: str
    parametric_answer: Optional[str] = None  # For SKIP: suggested answer template

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "parametric_answer": self.parametric_answer,
        }


class RetrievalDecider:
    """
    Decides if retrieval is needed for a query.

    Uses rule-based patterns by default, with optional LLM classifier
    for edge cases.
    """

    def __init__(self, config: SelfRAGConfig):
        self.config = config

        # Compile skip patterns from config
        self._skip_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in config.skip_patterns
        ]

        # Additional definitional patterns
        self._definitional_patterns = [
            re.compile(r"^what (?:is|are) (?:the )?(?:CAG|FRBM|PMAY|NHAI|FCI|GST|ITC|PFMS|NPA|RERA)\??$", re.I),
            re.compile(r"^what does (\w+) stand for\??$", re.I),
            re.compile(r"^define\b.*(?:CAG|FRBM|compliance|audit|performance)\b", re.I),
            re.compile(r"^how does (?:the )?(?:CAG|audit|government) work\??$", re.I),
            re.compile(r"^explain (?:the )?(?:role|function) of (?:CAG|audit)\??$", re.I),
            re.compile(r"^who is (?:the )?(?:CAG|Comptroller)\??$", re.I),
        ]

        # Multi-hop patterns (need multiple retrieval rounds)
        self._multi_hop_patterns = [
            re.compile(r"compare .+ and .+ and", re.I),  # 3+ entities
            re.compile(r"how .+ affected .+ which .+", re.I),  # Causal chain
            re.compile(r"what caused .+ and what were the effects", re.I),
            re.compile(r"analyze .+ across .+ and .+", re.I),
            re.compile(r"relationship between .+ and .+ and", re.I),
            re.compile(r"compare and analyze", re.I),  # Combined comparison + analysis
            re.compile(r"multiple factors", re.I),  # Indicates multi-faceted query
        ]

        # Acronym definitions for parametric answers
        self._acronym_definitions = {
            "cag": "CAG stands for Comptroller and Auditor General of India, the supreme audit institution responsible for auditing government accounts.",
            "frbm": "FRBM stands for Fiscal Responsibility and Budget Management Act, which sets fiscal discipline targets for the government.",
            "pmay": "PMAY stands for Pradhan Mantri Awas Yojana, a government housing scheme for affordable housing.",
            "nhai": "NHAI stands for National Highways Authority of India, responsible for development and management of national highways.",
            "fci": "FCI stands for Food Corporation of India, responsible for food grain procurement and distribution.",
            "gst": "GST stands for Goods and Services Tax, India's indirect tax system introduced in 2017.",
            "itc": "ITC stands for Input Tax Credit under GST, allowing businesses to claim credit for taxes paid on inputs.",
            "pfms": "PFMS stands for Public Financial Management System, a government platform for financial management.",
            "npa": "NPA stands for Non-Performing Assets, loans or advances where interest/principal remains overdue.",
            "rera": "RERA stands for Real Estate Regulatory Authority, established to regulate the real estate sector.",
        }

    def decide(self, query: str) -> DecisionResult:
        """
        Decide if retrieval is needed for the query.

        Args:
            query: User's question

        Returns:
            DecisionResult with decision, confidence, and reasoning
        """
        query_lower = query.lower().strip()
        query_stripped = query.strip()

        # Check skip patterns from config
        for pattern in self._skip_patterns:
            if pattern.match(query_stripped):
                parametric = self._get_parametric_answer(query_lower)
                return DecisionResult(
                    decision=RetrievalDecision.SKIP,
                    confidence=0.95,
                    reasoning=f"Matched skip pattern: {pattern.pattern}",
                    parametric_answer=parametric,
                )

        # Check definitional patterns
        for pattern in self._definitional_patterns:
            if pattern.match(query_stripped):
                parametric = self._get_parametric_answer(query_lower)
                return DecisionResult(
                    decision=RetrievalDecision.SKIP,
                    confidence=0.9,
                    reasoning="Definitional query - parametric knowledge sufficient",
                    parametric_answer=parametric,
                )

        # Check multi-hop patterns
        for pattern in self._multi_hop_patterns:
            if pattern.search(query_lower):
                return DecisionResult(
                    decision=RetrievalDecision.MULTI_RETRIEVE,
                    confidence=0.85,
                    reasoning=f"Complex query requiring multi-hop retrieval: {pattern.pattern}",
                )

        # Check for specific audit-related queries (always need retrieval)
        if self._requires_retrieval(query_lower):
            return DecisionResult(
                decision=RetrievalDecision.RETRIEVE,
                confidence=0.95,
                reasoning="Query requires specific audit report information",
            )

        # Default: standard retrieval
        return DecisionResult(
            decision=RetrievalDecision.RETRIEVE,
            confidence=0.8,
            reasoning="Standard query - retrieval recommended",
        )

    def _requires_retrieval(self, query_lower: str) -> bool:
        """Check if query definitely requires retrieval."""
        # Patterns that indicate specific audit information is needed
        retrieval_indicators = [
            r"₹",                           # Currency amounts
            r"\d+(?:,\d+)*\s*(?:crore|lakh)", # Indian number format
            r"revenue loss",
            r"audit (?:finding|observation|recommendation)",
            r"how much",
            r"what amount",
            r"toll plaza",
            r"ministry of",
            r"in \d{4}",                     # Year reference
            r"report (?:no|number)",
            r"paragraph \d+",
            r"section \d+",
            r"chapter \d+",
            r"specific",
            r"exact",
        ]

        return any(re.search(pattern, query_lower) for pattern in retrieval_indicators)

    def _get_parametric_answer(self, query_lower: str) -> Optional[str]:
        """Get parametric answer for definitional queries."""
        # Check for acronym queries
        for acronym, definition in self._acronym_definitions.items():
            if acronym in query_lower:
                return definition

        # Check for "what does X stand for" pattern
        match = re.search(r"what does (\w+) stand for", query_lower)
        if match:
            acronym = match.group(1).lower()
            if acronym in self._acronym_definitions:
                return self._acronym_definitions[acronym]

        return None

    def should_skip_retrieval(self, query: str) -> bool:
        """Quick check if retrieval should be skipped."""
        result = self.decide(query)
        return result.decision == RetrievalDecision.SKIP

    def should_use_agentic(self, query: str) -> bool:
        """Quick check if agentic multi-hop retrieval is needed."""
        result = self.decide(query)
        return result.decision == RetrievalDecision.MULTI_RETRIEVE


# =============================================================================
# PARAMETRIC RESPONSE GENERATOR
# =============================================================================


class ParametricResponder:
    """
    Generates responses for queries that don't need retrieval.

    Uses model's parametric knowledge for definitional and
    general knowledge queries about Indian government auditing.
    """

    # System prompt for parametric responses
    PARAMETRIC_SYSTEM_PROMPT = """You are an expert on Indian government auditing and the CAG (Comptroller and Auditor General).

Answer the following question using your knowledge of:
- Indian government audit procedures and terminology
- CAG's role and functions
- Common audit-related acronyms and concepts
- Government accounting and financial management

Provide a concise, accurate answer in 2-4 sentences.
Do NOT make up specific audit findings or amounts - only answer with general knowledge.
If the question requires specific audit report data, say: "This question requires information from specific audit reports. Please rephrase to ask about specific findings."
"""

    def __init__(self, llm_client=None, model: str = "gpt-4o-mini"):
        self.llm = llm_client
        self.model = model

    def respond(self, query: str, hint: Optional[str] = None) -> str:
        """
        Generate parametric response without retrieval.

        Args:
            query: User's question
            hint: Optional hint from RetrievalDecider (e.g., acronym definition)

        Returns:
            Generated response
        """
        # If we have a direct hint/definition, use it
        if hint:
            return hint

        # If no LLM client, return generic response
        if not self.llm:
            return self._get_fallback_response(query)

        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.PARAMETRIC_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=300,
                temperature=0.1,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Parametric response generation failed: {e}")
            return self._get_fallback_response(query)

    def _get_fallback_response(self, query: str) -> str:
        """Fallback response when LLM is unavailable."""
        query_lower = query.lower()

        # Check for common definitional queries
        if "cag" in query_lower:
            return (
                "The Comptroller and Auditor General (CAG) of India is the supreme audit "
                "institution, responsible for auditing government accounts at Union, State, "
                "and Local Body levels. The CAG reports to Parliament and State Legislatures."
            )

        if "frbm" in query_lower:
            return (
                "The Fiscal Responsibility and Budget Management (FRBM) Act sets fiscal "
                "discipline targets for the government, including limits on fiscal deficit "
                "and debt levels. States have adopted similar legislation."
            )

        return (
            "I can answer general questions about Indian government auditing. "
            "For specific audit findings, please ask about particular reports or findings."
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_retrieval_decider(config: SelfRAGConfig = None) -> RetrievalDecider:
    """Create a RetrievalDecider with default or custom config."""
    if config is None:
        config = SelfRAGConfig()
    return RetrievalDecider(config)


def quick_decide(query: str) -> str:
    """Quick decision for a query using default config."""
    decider = create_retrieval_decider()
    result = decider.decide(query)
    return result.decision.value
