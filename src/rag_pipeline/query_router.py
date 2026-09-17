"""
Query Router for CAG RAG Pipeline (SOTA Feature 2).

Routes queries to optimal retrieval strategy based on query intent:
- STANDARD_RAG: Default hybrid search for factual questions
- TEMPORAL: Cross-year comparisons and trend analysis
- ENTITY_COMPARATIVE: Entity-based comparisons (Railways vs NHAI)
- FILTERED_SEARCH: Strong filter signals (all issues in Gujarat)
- SUMMARY_ONLY: High-level overviews → RAPTOR hierarchical summaries

This improves retrieval quality by matching query type to optimal strategy.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, List

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from ..core.config import QueryRoutingConfig
except ImportError:
    from src.core.config import QueryRoutingConfig

logger = logging.getLogger(__name__)


class QueryRoute(Enum):
    """Available retrieval routes."""

    STANDARD_RAG = "standard_rag"       # Default hybrid search
    TEMPORAL = "temporal"                # Cross-year comparisons
    ENTITY_COMPARATIVE = "entity_graph"  # Entity-based comparison
    FILTERED_SEARCH = "filtered"         # Strong filter signal
    SUMMARY_ONLY = "summary"             # High-level overview → RAPTOR


@dataclass
class RoutingDecision:
    """Result of query routing classification."""

    route: QueryRoute
    confidence: float
    filters_suggested: Dict[str, Any]
    reasoning: str
    hierarchy_level: Optional[int] = None  # For SUMMARY_ONLY: 1=section, 2=chapter, 3=report

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route.value,
            "confidence": self.confidence,
            "filters_suggested": self.filters_suggested,
            "reasoning": self.reasoning,
            "hierarchy_level": self.hierarchy_level,
        }


# =============================================================================
# ROUTING PROMPT
# =============================================================================

ROUTING_PROMPT = """You are a query router for a CAG (Comptroller and Auditor General) audit report search system.

Classify the query into ONE of these routes:

1. **standard_rag** - Factual questions about specific findings, amounts, recommendations
   Examples: "What was the revenue loss at Nathavalasa toll plaza?", "How much money was lost?"

2. **temporal** - Queries involving time comparisons, trends, or changes over years
   Examples: "How has FRBM compliance changed from 2020 to 2024?", "What is the trend in toll revenue?"
   Keywords: trend, changed, over the years, compared to, evolution, progression, year over year

3. **entity_graph** - Entity comparisons between organizations, ministries, or departments
   Examples: "Compare Railways vs NHAI audit findings", "Which ministry has the most irregularities?"
   Keywords: compare, versus, vs, which is better, difference between (entities)

4. **filtered** - Strong filter signal where the user wants all items matching criteria
   Examples: "All GST issues in Gujarat", "Show me revenue losses in Maharashtra"
   Keywords: all, every, list all, show me all, in [state name]

5. **summary** - High-level overview or summary questions (use RAPTOR hierarchical summaries)
   Examples: "Summarize the main themes", "What are the key findings?", "Give me an overview"
   Keywords: summarize, summary, overview, main themes, key findings, briefly, in brief

For **summary** route, also determine the appropriate hierarchy_level:
- 3 = report-level ("summarize the entire NHAI audit", "overall summary")
- 2 = chapter-level ("what does Chapter 3 cover?", "main findings") [DEFAULT]
- 1 = section-level ("summarize revenue collection findings", specific topic)

Also extract any filters you detect:
- state_name: If a state is mentioned (e.g., "Gujarat", "Maharashtra")
- audit_year: If a year or year range is mentioned (e.g., "2023-24", "2020 to 2024")
- finding_type: If a specific type is mentioned (loss_of_revenue, compliance, performance)
- department: If a department/ministry is mentioned (NHAI, Railways, FCI)

Return your analysis as JSON:
{
    "route": "standard_rag|temporal|entity_graph|filtered|summary",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation of why this route was chosen",
    "filters": {
        "state_name": null or "State Name",
        "audit_year": null or "YYYY-YY",
        "finding_type": null or "type",
        "department": null or "Department"
    },
    "hierarchy_level": null or 1|2|3
}
"""


class QueryRouter:
    """
    Routes queries to optimal retrieval strategy.

    Uses a lightweight LLM classifier (Gemini 3.5 Flash-Lite) for intelligent routing,
    with rule-based fallbacks for common patterns.
    """

    def __init__(
        self,
        config: QueryRoutingConfig,
        openai_client: Optional[OpenAI] = None,
    ):
        self.config = config
        self.openai = openai_client
        self._gemini_client = None  # Lazy-initialized

        # Check if model is Gemini-based (use Gemini API)
        self._use_gemini = self.config.model.startswith("gemini-")

        # Rule-based patterns for fast routing (no LLM call needed)
        self._temporal_patterns = [
            r"how has .+ changed",
            r"trend",
            r"over the years",
            r"year[\s-]over[\s-]year",
            r"from \d{4} to \d{4}",
            r"between \d{4} and \d{4}",
            r"evolution",
            r"progression",
            r"compared to (last|previous|earlier) year",
        ]

        self._summary_patterns = [
            r"summarize",
            r"summary",
            r"overview",
            r"main themes",
            r"key findings",
            r"key issues",
            r"main findings",
            r"major issues",
            r"give me an overview",
            r"briefly describe",
            r"in brief",
            r"high[\s-]level",
            r"tell me about the report",
            r"what are the .*(findings|issues|themes)",
        ]

        self._entity_patterns = [
            r"compare .+ (vs|versus|with|and) .+",
            r"which (ministry|department|organization) has",
            r"(railways|nhai|fci) (vs|versus|compared to)",
            r"difference between .+ and .+",
        ]

        self._filtered_patterns = [
            r"^(all|every|list all|show me all)",
            r"all .+ in (gujarat|maharashtra|kerala|tamil nadu|karnataka)",
            r"issues in \w+",
            r"findings (in|from|for) \w+",
        ]

    def route(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RoutingDecision:
        """
        Classify query and determine optimal retrieval route.

        Args:
            query: User's question
            context: Optional context (e.g., current report, previous queries)

        Returns:
            RoutingDecision with route, confidence, and suggested filters
        """
        query_lower = query.lower().strip()

        # Try rule-based routing first (fast path)
        rule_result = self._route_by_rules(query_lower)
        if rule_result and rule_result.confidence >= self.config.min_confidence:
            logger.info(f"Rule-based routing: {rule_result.route.value} ({rule_result.confidence:.2f})")
            return rule_result

        # Fall back to LLM routing
        if self._use_gemini or self.openai:
            try:
                if self._use_gemini:
                    llm_result = self._route_by_gemini(query)
                else:
                    llm_result = self._route_by_llm(query)
                if llm_result:
                    logger.info(f"LLM routing: {llm_result.route.value} ({llm_result.confidence:.2f})")
                    return llm_result
            except Exception as e:
                logger.warning(f"LLM routing failed: {e}")
                if not self.config.fallback_on_error:
                    raise

        # Final fallback: standard RAG
        return RoutingDecision(
            route=QueryRoute.STANDARD_RAG,
            confidence=0.5,
            filters_suggested={},
            reasoning="Fallback to standard RAG",
        )

    def _route_by_rules(self, query_lower: str) -> Optional[RoutingDecision]:
        """Fast rule-based routing using regex patterns."""

        # Check temporal patterns
        for pattern in self._temporal_patterns:
            if re.search(pattern, query_lower):
                years = self._extract_years(query_lower)
                return RoutingDecision(
                    route=QueryRoute.TEMPORAL,
                    confidence=0.85,
                    filters_suggested={"years": years} if years else {},
                    reasoning=f"Matched temporal pattern: {pattern}",
                )

        # Check summary patterns
        for pattern in self._summary_patterns:
            if re.search(pattern, query_lower):
                level = self._detect_hierarchy_level(query_lower)
                return RoutingDecision(
                    route=QueryRoute.SUMMARY_ONLY,
                    confidence=0.9,
                    filters_suggested={},
                    reasoning=f"Matched summary pattern: {pattern}",
                    hierarchy_level=level,
                )

        # Check entity comparison patterns
        for pattern in self._entity_patterns:
            if re.search(pattern, query_lower):
                entities = self._extract_entities(query_lower)
                return RoutingDecision(
                    route=QueryRoute.ENTITY_COMPARATIVE,
                    confidence=0.8,
                    filters_suggested={"entities": entities} if entities else {},
                    reasoning=f"Matched entity comparison pattern: {pattern}",
                )

        # Check filtered search patterns
        for pattern in self._filtered_patterns:
            if re.search(pattern, query_lower):
                state = self._extract_state(query_lower)
                return RoutingDecision(
                    route=QueryRoute.FILTERED_SEARCH,
                    confidence=0.85,
                    filters_suggested={"state_name": state} if state else {},
                    reasoning=f"Matched filtered search pattern: {pattern}",
                )

        return None

    @property
    def gemini_client(self):
        """Lazy-initialize Gemini client."""
        if self._gemini_client is None:
            try:
                from google import genai
                self._gemini_client = genai.Client()
            except ImportError:
                raise ImportError("Install google-genai: pip install google-genai")
        return self._gemini_client

    def _route_by_gemini(self, query: str) -> Optional[RoutingDecision]:
        """Use Gemini for intelligent routing (GCP credit billing)."""
        import json
        from google.genai import types

        combined_prompt = f"{ROUTING_PROMPT}\n\n---\n\nQuery: {query}\n\nRespond with ONLY valid JSON."

        response = self.gemini_client.models.generate_content(
            model=self.config.model,
            contents=[types.Part.from_text(text=combined_prompt)],
            config=types.GenerateContentConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                response_mime_type="application/json",
            ),
        )

        content = response.text.strip()
        result = json.loads(content)

        route_str = result.get("route", "standard_rag")
        try:
            route = QueryRoute(route_str)
        except ValueError:
            route = QueryRoute.STANDARD_RAG

        return RoutingDecision(
            route=route,
            confidence=result.get("confidence", 0.7),
            filters_suggested=result.get("filters", {}),
            reasoning=result.get("reasoning", "Gemini classification"),
            hierarchy_level=result.get("hierarchy_level"),
        )

    def _route_by_llm(self, query: str) -> Optional[RoutingDecision]:
        """Use OpenAI LLM for intelligent routing (fallback)."""
        import json

        response = self.openai.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": ROUTING_PROMPT},
                {"role": "user", "content": query},
            ],
            response_format={"type": "json_object"},
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )

        content = response.choices[0].message.content
        result = json.loads(content)

        route_str = result.get("route", "standard_rag")
        try:
            route = QueryRoute(route_str)
        except ValueError:
            route = QueryRoute.STANDARD_RAG

        return RoutingDecision(
            route=route,
            confidence=result.get("confidence", 0.7),
            filters_suggested=result.get("filters", {}),
            reasoning=result.get("reasoning", "LLM classification"),
            hierarchy_level=result.get("hierarchy_level"),
        )

    def _extract_years(self, query: str) -> List[str]:
        """Extract year references from query."""
        # Match patterns like "2023-24", "2023", "2020 to 2024"
        patterns = [
            r"(\d{4}-\d{2})",  # 2023-24
            r"(\d{4})",        # 2023
        ]
        years = []
        for pattern in patterns:
            matches = re.findall(pattern, query)
            years.extend(matches)
        return list(set(years))

    def _extract_state(self, query: str) -> Optional[str]:
        """Extract state name from query."""
        states = [
            "andhra pradesh", "arunachal pradesh", "assam", "bihar",
            "chhattisgarh", "goa", "gujarat", "haryana", "himachal pradesh",
            "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra",
            "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "punjab",
            "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
            "uttar pradesh", "uttarakhand", "west bengal",
        ]

        query_lower = query.lower()
        for state in states:
            if state in query_lower:
                return state.title()

        return None

    def _extract_entities(self, query: str) -> List[str]:
        """Extract entity names from comparison query."""
        known_entities = [
            "railways", "nhai", "fci", "ministry of defence",
            "ministry of finance", "coal india", "ongc", "ntpc",
            "steel authority", "bharat petroleum", "hindustan petroleum",
        ]

        query_lower = query.lower()
        found = []
        for entity in known_entities:
            if entity in query_lower:
                found.append(entity.upper() if len(entity) <= 4 else entity.title())
        return found

    def _detect_hierarchy_level(self, query: str) -> int:
        """Detect appropriate hierarchy level for summary queries."""
        # Report-level (L3)
        if any(p in query for p in ["entire report", "whole report", "overall summary"]):
            return 3

        # Section-level (L1)
        if any(p in query for p in ["specific", "section", "detailed"]):
            return 1

        # Default: chapter level (L2)
        return 2


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def should_use_hierarchical(decision: RoutingDecision) -> bool:
    """Check if routing decision indicates hierarchical retrieval."""
    return decision.route == QueryRoute.SUMMARY_ONLY


def should_use_entity_graph(decision: RoutingDecision) -> bool:
    """Check if routing decision indicates entity graph retrieval."""
    return decision.route == QueryRoute.ENTITY_COMPARATIVE


def should_use_temporal(decision: RoutingDecision) -> bool:
    """Check if routing decision indicates temporal retrieval."""
    return decision.route == QueryRoute.TEMPORAL


def get_route_description(route: QueryRoute) -> str:
    """Get human-readable description of a route."""
    descriptions = {
        QueryRoute.STANDARD_RAG: "Standard hybrid search",
        QueryRoute.TEMPORAL: "Cross-year temporal analysis",
        QueryRoute.ENTITY_COMPARATIVE: "Entity-based comparison",
        QueryRoute.FILTERED_SEARCH: "Filtered search with strong signals",
        QueryRoute.SUMMARY_ONLY: "Hierarchical summary retrieval (RAPTOR)",
    }
    return descriptions.get(route, "Unknown route")
