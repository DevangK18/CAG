"""
Query Enhancement Service
==========================
Single LLM call that provides:
1. Question type classification (replaces regex _detect_question_type)
2. Query expansion (2 additional search queries)
3. Filter suggestions (report_id hints, finding_type, temporal scope)
4. Retrieval parameter recommendations (top_k, context_limit)

IMPORTANT: This is ONE call to GPT-4o-mini per query (~$0.0002).
Cost: ~$0.0002/query (single GPT-4o-mini call) + zero-cost algorithmic improvements
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from openai import OpenAI

try:
    from ..core.config import QueryEnhancementConfig, LLMProvider
except ImportError:
    from src.core.config import QueryEnhancementConfig, LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class QueryEnhancement:
    """Output of the query enhancement step."""

    # Question classification
    question_type: str  # factual, list, aggregation, comparison, explanation, procedural

    # Expanded queries for multi-query retrieval
    expanded_queries: List[str]  # Always includes original as first element

    # Filter suggestions
    suggested_filters: Dict[str, Any]  # e.g., {"finding_type": "loss_of_revenue"}

    # Retrieval parameters
    top_k: int = 10
    initial_candidates: int = 50
    max_context_chars: int = 15000

    # Style recommendation
    recommended_style: Optional[str] = None  # Only set if style is "adaptive"

    # Raw response for debugging
    raw_response: Optional[str] = None


# System prompt for the single enhancement call
ENHANCEMENT_SYSTEM_PROMPT = """You analyze questions about Indian CAG (Comptroller and Auditor General) audit reports.

Return ONLY valid JSON (no markdown, no backticks) with this exact schema:
{
  "question_type": "factual|list|aggregation|comparison|explanation|procedural",
  "expanded_queries": ["original query reworded for search", "alternative phrasing with domain terms"],
  "suggested_filters": {},
  "retrieval_params": {"top_k": 10, "initial_candidates": 50, "max_context_chars": 15000},
  "recommended_style": "concise|detailed|executive|technical|comparative|explanatory"
}

Rules for expanded_queries:
- Generate exactly 2 alternative queries (the original is added automatically)
- Rephrase using CAG/audit domain vocabulary (e.g., "money lost" → "revenue loss quantified in crore")
- Include specific terms likely in audit reports (findings, observations, recommendations, compliance)
- If the query mentions an entity, include its full name AND acronym in different queries

Rules for suggested_filters:
- Only include filters you're confident about. Empty {} is fine.
- Valid filter keys: "finding_type" (loss_of_revenue|non_compliance|fraud_misappropriation|wasteful_expenditure|performance_shortfall), "severity" (critical|high|medium|low)
- Do NOT guess report_id — leave that to the caller

Rules for retrieval_params:
- factual: {"top_k": 8, "initial_candidates": 30, "max_context_chars": 10000}
- list/aggregation: {"top_k": 18, "initial_candidates": 80, "max_context_chars": 25000}
- comparison: {"top_k": 15, "initial_candidates": 60, "max_context_chars": 22000}
- explanation: {"top_k": 12, "initial_candidates": 50, "max_context_chars": 18000}
- procedural: {"top_k": 10, "initial_candidates": 40, "max_context_chars": 15000}

Rules for recommended_style:
- factual → "concise", list → "detailed", aggregation → "executive"
- comparison → "comparative", explanation → "explanatory", procedural → "technical"
"""


class QueryEnhancer:
    """
    Single-call query intelligence.

    Usage:
        enhancer = QueryEnhancer(config, openai_client)
        enhancement = enhancer.enhance("What went wrong with toll collection?")
        # enhancement.expanded_queries = ["What went wrong with toll collection?", "toll revenue loss audit findings NHAI", "fee collection shortfall compliance observations"]
        # enhancement.question_type = "explanation"
        # enhancement.suggested_filters = {"finding_type": "loss_of_revenue"}
    """

    def __init__(self, config: QueryEnhancementConfig, openai_client: OpenAI):
        self.config = config
        self.openai_client = openai_client
        self._gemini_client = None  # Lazy-initialized

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

    def enhance(self, query: str, style: str = "adaptive") -> QueryEnhancement:
        """
        Enhance a query with a single LLM call.

        If enhancement is disabled or fails, returns a safe fallback
        with the original query and default parameters.
        """
        if not self.config.enabled:
            return self._fallback(query)

        try:
            user_prompt = f'Question: "{query}"'
            if style != "adaptive":
                user_prompt += f"\n(User selected style: {style} — do NOT override recommended_style)"

            # Route to appropriate provider
            if self.config.provider == LLMProvider.GEMINI:
                raw = self._enhance_with_gemini(user_prompt)
            else:
                raw = self._enhance_with_openai(user_prompt)

            parsed = json.loads(raw)

            # Build expanded queries: original first, then expansions
            expanded = [query]  # Original always first
            for eq in parsed.get("expanded_queries", []):
                if eq and eq != query:
                    expanded.append(eq)
            # Ensure we have at least the original
            expanded = expanded[: self.config.num_expansions]

            # Extract retrieval params with defaults
            ret_params = parsed.get("retrieval_params", {})

            enhancement = QueryEnhancement(
                question_type=parsed.get("question_type", "factual"),
                expanded_queries=expanded,
                suggested_filters=parsed.get("suggested_filters", {}),
                top_k=ret_params.get("top_k", 10),
                initial_candidates=ret_params.get("initial_candidates", 50),
                max_context_chars=ret_params.get("max_context_chars", 15000),
                recommended_style=parsed.get("recommended_style")
                if style == "adaptive"
                else None,
                raw_response=raw,
            )

            logger.info(
                f"QueryEnhancer: type={enhancement.question_type}, "
                f"queries={len(enhancement.expanded_queries)}, "
                f"filters={enhancement.suggested_filters}, "
                f"top_k={enhancement.top_k}"
            )

            return enhancement

        except Exception as e:
            logger.warning(f"QueryEnhancer failed, using fallback: {e}")
            return self._fallback(query)

    def _enhance_with_openai(self, user_prompt: str) -> str:
        """Call OpenAI for query enhancement."""
        response = self.openai_client.chat.completions.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            messages=[
                {"role": "system", "content": ENHANCEMENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    def _enhance_with_gemini(self, user_prompt: str) -> str:
        """Call Gemini for query enhancement."""
        from google.genai import types

        # Gemini uses combined prompt
        combined_prompt = f"{ENHANCEMENT_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}\n\nRespond with ONLY valid JSON, no markdown."

        response = self.gemini_client.models.generate_content(
            model=self.config.gemini_model,
            contents=[types.Part.from_text(text=combined_prompt)],
            config=types.GenerateContentConfig(
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                response_mime_type="application/json",
            ),
        )
        return response.text.strip()

    def _fallback(self, query: str) -> QueryEnhancement:
        """Safe fallback when enhancement is disabled or fails."""
        return QueryEnhancement(
            question_type="factual",
            expanded_queries=[query],
            suggested_filters={},
            top_k=10,
            initial_candidates=50,
            max_context_chars=15000,
        )
