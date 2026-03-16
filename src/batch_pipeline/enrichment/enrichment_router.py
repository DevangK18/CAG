"""
EnrichmentRouter: Intelligent chunk routing for LLM enrichment.

Decides which chunks need LLM processing and routes to appropriate provider:
- High volume, simple tasks → OpenAI Batch (GPT-4o-mini, free/cheap)
- Complex reasoning tasks → Anthropic Batch (Sonnet, 50% discount)
- Already extracted/low value → Skip (no LLM needed)

Routing Logic:
1. Skip tables (already structured in Phase 1)
2. Skip chunks with existing findings (Phase 1)
3. Check for finding signals (explicit patterns)
4. Check for implicit signals (variance, pending issues)
5. Check for complex analysis needs (systemic issues)
6. Route based on signal scores and report type
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Literal
from enum import Enum


class EnrichmentTask(str, Enum):
    """Types of enrichment tasks."""

    FINDING_EXTRACTION = "finding_extraction"
    IMPLICIT_FINDING = "implicit_finding"
    ENTITY_EXTRACTION = "entity_extraction"
    COMPLEX_ANALYSIS = "complex_analysis"


@dataclass
class RoutingDecision:
    """Routing decision for a chunk."""

    chunk_id: str
    task: EnrichmentTask
    provider: Literal["openai", "anthropic", "skip"]
    priority: int  # 1=high, 2=medium, 3=low
    reason: str
    confidence_score: float = 0.0  # Pattern matching confidence


class EnrichmentRouter:
    """
    Decides which chunks need LLM enrichment and routes to appropriate provider.

    Routing Strategy:
    - Skip: Tables (structured), existing findings, low-value content
    - OpenAI: High volume finding extraction, implicit finding detection
    - Anthropic: Complex analysis requiring deep reasoning

    Usage:
        router = EnrichmentRouter(report_type="compliance")
        decisions = router.route_chunks(chunks, existing_findings)

        # Filter by provider
        openai_chunks = [d for d in decisions if d.provider == "openai"]
        anthropic_chunks = [d for d in decisions if d.provider == "anthropic"]
    """

    # ==================== PATTERN DEFINITIONS ====================

    # Patterns that indicate chunk might contain explicit findings
    FINDING_SIGNALS = [
        r"audit\s+(?:revealed|observed|found|noticed|detected)",
        r"(?:loss|damage|wastage|leakage)\s+of\s+(?:₹|Rs\.?|INR)",
        r"₹\s*[\d.,]+\s*(?:crore|lakh)",
        r"(?:non-?compliance|violation|deviation|breach)",
        r"(?:irregular|unauthorized|excess|unwarranted|unjustified)",
        r"(?:fraud|misappropriation|embezzlement)",
        r"(?:deficiency|deficiencies|lapse|lapses)",
    ]

    # Patterns for implicit findings (issues not explicitly labeled)
    IMPLICIT_SIGNALS = [
        r"(?:variance|difference|gap|shortfall|excess)\s+of\s+(?:₹|Rs\.?|INR|\d)",
        r"(?:shortfall|excess)\s+against\s+(?:target|budget|allocation)",
        r"(?:pending|outstanding|delayed)\s+(?:since|for|from)",
        r"(?:no|lack\s+of|absence\s+of)\s+(?:records?|documentation|evidence|proof)",
        r"(?:failed|did\s+not)\s+(?:submit|provide|maintain|comply)",
        r"(?:target|objective)\s+(?:not\s+)?(?:achieved|met|fulfilled)",
    ]

    # Patterns for complex analysis needs
    COMPLEX_SIGNALS = [
        r"(?:systematic|systemic|recurring|persistent)\s+(?:issue|problem|failure|deficiency)",
        r"(?:multiple|several|numerous)\s+(?:instances|cases|occurrences)",
        r"(?:policy|procedural|regulatory)\s+(?:implications|recommendations|changes)",
        r"(?:root\s+cause|underlying\s+reason|systemic\s+failure)",
        r"(?:across|spanning)\s+(?:departments|ministries|states|years)",
    ]

    # Patterns indicating high-value content for entity extraction
    ENTITY_SIGNALS = [
        r"(?:Ministry|Department|Directorate)\s+of\s+\w+",
        r"(?:Government\s+of|State\s+of)\s+\w+",
        r"(?:scheme|programme|project|initiative)\s*:\s*\w+",
        r"(?:PSU|Public\s+Sector\s+Undertaking)",
    ]

    def __init__(self, report_type: str = "general"):
        """
        Initialize router with report type for type-specific routing.

        Args:
            report_type: One of "compliance", "performance", "financial", "general"
        """
        self.report_type = report_type.lower()
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        self.finding_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.FINDING_SIGNALS
        ]
        self.implicit_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.IMPLICIT_SIGNALS
        ]
        self.complex_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.COMPLEX_SIGNALS
        ]
        self.entity_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.ENTITY_SIGNALS
        ]

    def route_chunks(
        self, chunks: List[Dict], existing_findings: List[Dict]
    ) -> List[RoutingDecision]:
        """
        Analyze chunks and decide routing.

        Args:
            chunks: List of ChildChunk dicts from chunking service
            existing_findings: Findings already extracted by Phase 1

        Returns:
            List of routing decisions (skip, openai, anthropic)
        """
        decisions = []
        existing_chunk_ids = {f.get("source_chunk_id") for f in existing_findings}

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            content = chunk.get("content", "")
            content_type = chunk.get("content_type", "text")

            # ==================== SKIP RULES ====================

            # Skip tables (already structured in Phase 1 P0-1)
            if content_type == "table_markdown":
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.FINDING_EXTRACTION,
                        provider="skip",
                        priority=3,
                        reason="Table already structured in Phase 1",
                        confidence_score=0.0,
                    )
                )
                continue

            # Skip if already has finding from Phase 1
            if chunk_id in existing_chunk_ids:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.FINDING_EXTRACTION,
                        provider="skip",
                        priority=3,
                        reason="Finding already extracted in Phase 1",
                        confidence_score=0.0,
                    )
                )
                continue

            # Skip very short content (< 50 chars)
            if len(content) < 50:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.FINDING_EXTRACTION,
                        provider="skip",
                        priority=3,
                        reason="Content too short for meaningful extraction",
                        confidence_score=0.0,
                    )
                )
                continue

            # ==================== PATTERN SCORING ====================

            finding_score = self._score_patterns(content, self.finding_patterns)
            implicit_score = self._score_patterns(content, self.implicit_patterns)
            complex_score = self._score_patterns(content, self.complex_patterns)
            entity_score = self._score_patterns(content, self.entity_patterns)

            # ==================== ROUTING LOGIC ====================

            # Complex analysis → Anthropic (deep reasoning needed)
            if complex_score > 0.4:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.COMPLEX_ANALYSIS,
                        provider="anthropic",
                        priority=1,
                        reason=f"Complex analysis signals detected (score={complex_score:.2f})",
                        confidence_score=complex_score,
                    )
                )

            # Finding extraction → OpenAI (high volume, simple)
            elif finding_score > 0.3:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.FINDING_EXTRACTION,
                        provider="openai",
                        priority=1,
                        reason=f"Finding signals detected (score={finding_score:.2f})",
                        confidence_score=finding_score,
                    )
                )

            # Implicit finding → OpenAI (variance, pending issues)
            elif implicit_score > 0.3:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.IMPLICIT_FINDING,
                        provider="openai",
                        priority=2,
                        reason=f"Implicit signals detected (score={implicit_score:.2f})",
                        confidence_score=implicit_score,
                    )
                )

            # Entity extraction → OpenAI (ministries, schemes)
            elif entity_score > 0.3:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.ENTITY_EXTRACTION,
                        provider="openai",
                        priority=2,
                        reason=f"Entity signals detected (score={entity_score:.2f})",
                        confidence_score=entity_score,
                    )
                )

            # Low value → Skip
            else:
                decisions.append(
                    RoutingDecision(
                        chunk_id=chunk_id,
                        task=EnrichmentTask.FINDING_EXTRACTION,
                        provider="skip",
                        priority=3,
                        reason="No enrichment signals detected",
                        confidence_score=0.0,
                    )
                )

        return decisions

    def _score_patterns(self, text: str, patterns: List[re.Pattern]) -> float:
        """
        Score text against pattern list.

        Returns:
            Score between 0.0 and 1.0 based on pattern matches
        """
        if not patterns:
            return 0.0

        matches = sum(1 for p in patterns if p.search(text))
        return matches / len(patterns)

    def get_routing_statistics(self, decisions: List[RoutingDecision]) -> Dict:
        """
        Get summary statistics for routing decisions.

        Returns:
            Dict with counts by provider and task
        """
        stats = {
            "total_chunks": len(decisions),
            "by_provider": {"skip": 0, "openai": 0, "anthropic": 0},
            "by_task": {},
            "average_confidence": {
                "openai": 0.0,
                "anthropic": 0.0,
            },
        }

        openai_scores = []
        anthropic_scores = []

        for decision in decisions:
            stats["by_provider"][decision.provider] += 1
            task_name = decision.task.value
            stats["by_task"][task_name] = stats["by_task"].get(task_name, 0) + 1

            if decision.provider == "openai":
                openai_scores.append(decision.confidence_score)
            elif decision.provider == "anthropic":
                anthropic_scores.append(decision.confidence_score)

        if openai_scores:
            stats["average_confidence"]["openai"] = sum(openai_scores) / len(
                openai_scores
            )
        if anthropic_scores:
            stats["average_confidence"]["anthropic"] = sum(anthropic_scores) / len(
                anthropic_scores
            )

        return stats
