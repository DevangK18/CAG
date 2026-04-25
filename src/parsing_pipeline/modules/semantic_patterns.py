"""
Enhanced Semantic Pattern Matching for CAG Audit Reports.

This module provides comprehensive pattern matching for finding extraction,
especially targeting implicit findings in compliance audit reports that
currently show 0 findings.

Part of Phase 1 Enhancement (P1-2: Enhanced Semantic Patterns)
"""

import re
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass

# Import report type profiles for confidence boosting
from src.parsing_pipeline.modules import report_type_profiles


# ═══════════════════════════════════════════════════════════════════════
# EXPLICIT FINDING PATTERNS (High Confidence)
# ═══════════════════════════════════════════════════════════════════════

EXPLICIT_PATTERNS = {
    "audit_revealed": {
        "patterns": [
            r"audit\s+(?:revealed|observed|noticed|found|disclosed)",
            r"(?:scrutiny|examination|review)\s+(?:revealed|showed|indicated)",
            r"(?:it\s+was|we)\s+(?:observed|noticed|found)\s+that",
            r"test\s+check\s+(?:revealed|disclosed|showed)",
            r"on\s+verification\s+it\s+was\s+(?:found|seen|observed)",
        ],
        "confidence": 0.4,
        "description": "Explicit audit observation statements",
    },
    "non_compliance": {
        "patterns": [
            r"(?:non-?compliance|violation|deviation|departure)\s+(?:with|from|of)",
            r"contrary\s+to\s+(?:the\s+)?(?:provisions?|rules?|guidelines?)",
            r"in\s+(?:violation|contravention)\s+of",
            r"not\s+in\s+(?:accordance|conformity)\s+with",
            r"failed\s+to\s+comply\s+with",
            r"in\s+disregard\s+of",
        ],
        "confidence": 0.3,
        "description": "Non-compliance with rules/regulations",
    },
    "loss_damage": {
        "patterns": [
            r"(?:loss|damage|wastage)\s+of\s+₹?\s*[\d.,]+\s*(?:crore|lakh)?",
            r"(?:avoidable|undue|extra)\s+(?:expenditure|payment|burden)",
            r"(?:resulted|led)\s+(?:in|to)\s+(?:loss|damage)",
            r"(?:infructuous|unfruitful)\s+expenditure",
            r"blocking\s+of\s+funds",
        ],
        "confidence": 0.3,
        "description": "Financial loss or damage",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# IMPLICIT FINDING PATTERNS (Medium Confidence)
# These are critical for compliance reports with 0 findings
# ═══════════════════════════════════════════════════════════════════════

IMPLICIT_PATTERNS = {
    "variance_issue": {
        "patterns": [
            r"(?:variance|difference|gap)\s+of\s+₹?\s*[\d.,]+",
            r"(?:shortfall|excess)\s+of\s+₹?\s*[\d.,]+",
            r"(?:actual|expenditure)\s+(?:was|were)\s+(?:higher|lower|less|more)\s+(?:than|by)",
            r"(?:under|over)[\s-]?(?:statement|assessment|valuation)",
            r"(?:un)?reconciled\s+(?:difference|amount|balance)",
        ],
        "confidence": 0.25,
        "description": "Variance and discrepancy issues",
    },
    "target_miss": {
        "patterns": [
            r"(?:target|objective|goal)\s+(?:was|were)\s+not\s+(?:achieved|met|attained)",
            r"(?:achievement|progress)\s+(?:was|were)\s+(?:only|merely)\s+\d+%?",
            r"against\s+(?:the\s+)?target\s+of.*(?:only|merely)",
            r"(?:fell\s+short|shortfall)\s+(?:of|by|against)\s+target",
            r"(?:below|under)\s+(?:the\s+)?(?:target|benchmark|norm)",
        ],
        "confidence": 0.2,
        "description": "Target non-achievement",
    },
    "procedural_lapse": {
        "patterns": [
            r"(?:without|in\s+absence\s+of)\s+(?:proper|required|necessary)\s+(?:approval|sanction)",
            r"(?:records?|documents?)\s+(?:were|was)\s+not\s+(?:maintained|available|produced)",
            r"(?:no|lack\s+of)\s+(?:evidence|proof|documentation)",
            r"(?:absence|non-?existence)\s+of\s+(?:mechanism|system|procedure)",
            r"(?:no|not)\s+(?:intimation|information|intimated|informed)",
        ],
        "confidence": 0.2,
        "description": "Procedural irregularities",
    },
    "pending_issue": {
        "patterns": [
            r"(?:pending|outstanding|overdue)\s+(?:since|for)\s+(?:more\s+than\s+)?\d+\s+(?:years?|months?)",
            r"(?:no\s+action|action\s+not)\s+taken\s+(?:till|as\s+of)\s+date",
            r"(?:remained|lying)\s+(?:unresolved|pending|unsettled)",
            r"(?:not\s+yet|yet\s+to\s+be)\s+(?:resolved|settled|completed)",
            r"(?:awaiting|pending)\s+(?:approval|clearance|decision)",
        ],
        "confidence": 0.15,
        "description": "Pending and unresolved issues",
    },
    "delay_issue": {
        "patterns": [
            r"delay\s+(?:of|ranging\s+from)\s+\d+\s+(?:days|months|years)",
            r"(?:inordinate|undue|excessive)\s+delay",
            r"delayed\s+by\s+\d+\s+(?:days|months|years)",
            r"(?:not|yet\s+to\s+be)\s+(?:completed|executed|implemented)\s+(?:even\s+)?after\s+\d+",
            r"(?:project|work)\s+(?:was|were)\s+(?:delayed|pending)",
        ],
        "confidence": 0.15,
        "description": "Delays in execution",
    },
    "irregular_expenditure": {
        "patterns": [
            r"(?:irregular|improper|unauthorized)\s+(?:expenditure|payment|spending)",
            r"expenditure\s+(?:incurred|made)\s+without\s+(?:approval|sanction)",
            r"(?:un)?sanctioned\s+expenditure",
            r"payment\s+made\s+without\s+(?:adequate|proper)\s+(?:justification|documentation)",
        ],
        "confidence": 0.25,
        "description": "Irregular financial transactions",
    },
    "system_weakness": {
        "patterns": [
            r"(?:weak|inadequate|deficient)\s+(?:internal\s+)?control(?:s)?",
            r"(?:absence|lack)\s+of\s+(?:monitoring|oversight|supervision)",
            r"(?:no|not)\s+(?:mechanism|system)\s+(?:exists?|in\s+place)",
            r"(?:deficiency|deficiencies)\s+in\s+(?:the\s+)?system",
        ],
        "confidence": 0.15,
        "description": "System and control deficiencies",
    },
    # State/Local-specific implicit patterns
    "benefit_deprivation": {
        "patterns": [
            r"(?:were|was)\s+deprived\s+of\s+(?:this\s+)?(?:benefit|allowance)",
            r"eligible\s+.{0,20}(?:were|was)\s+(?:not\s+provided|deprived|denied)",
            r"(?:CwSN|children|students?|beneficiar)\s+.{0,20}(?:deprived|not\s+provided)",
            r"transferred\s+.{0,20}(?:dormant|wrong)\s+.{0,15}accounts?",
        ],
        "confidence": 0.25,
        "description": "Beneficiaries denied entitled benefits",
    },
    "gst_tax_issue": {
        "patterns": [
            r"mismatch\s+(?:of|in)\s+(?:ITC|tax\s+liability)",
            r"irregular\s+claim(?:ing)?\s+of\s+(?:ITC|Input\s+Tax\s+Credit)",
            r"(?:compliance\s+)?(?:discrepanc|deficienc)(?:y|ies)\s+.{0,20}(?:tax|ITC|GST)",
            r"turnover\s+(?:escape|mismatch|difference)",
            r"unreconciled\s+(?:ITC|payment\s+of\s+tax)",
        ],
        "confidence": 0.25,
        "description": "GST/ITC compliance issues",
    },
    "record_keeping_failure": {
        "patterns": [
            r"(?:registers?|records?|accounts?)\s+.{0,20}not\s+maintained",
            r"items?\s+.{0,20}not\s+accounted\s+for",
            r"figures?\s+.{0,20}did\s+not\s+match",
            r"budget\s+estimates?\s+.{0,15}not\s+(?:prepared|passed)",
            r"UCs?\s+.{0,15}(?:pending|not\s+submitted)",
        ],
        "confidence": 0.2,
        "description": "Record-keeping and accounting failures",
    },
    "monitoring_failure": {
        "patterns": [
            r"(?:meetings?|committee)\s+.{0,15}(?:were|was)\s+not\s+held",
            r"internal\s+audit\s+.{0,15}not\s+(?:planned|conducted)",
            r"(?:survey|inspection)\s+.{0,15}not\s+(?:conducted|done)",
            r"(?:no|not\s+any)\s+(?:effective\s+)?action\s+.{0,15}(?:taken|initiated)",
        ],
        "confidence": 0.2,
        "description": "Monitoring and oversight failures",
    },
    "procurement_issue": {
        "patterns": [
            r"purchased\s+.{0,20}without\s+(?:inviting\s+)?(?:quotations?|tenders?)",
            r"(?:quotations?|tenders?)\s+.{0,15}not\s+(?:invited|obtained)",
            r"payment\s+.{0,15}without\s+(?:deducting|recovering)\s+TDS",
        ],
        "confidence": 0.2,
        "description": "Procurement procedure violations",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# MONETARY VALUE PATTERNS
# ═══════════════════════════════════════════════════════════════════════

MONETARY_PATTERNS = [
    r"[₹`]\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand)?",
    r"Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand)?",
    r"INR\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand)?",
    r"([\d,]+(?:\.\d+)?)\s*(crore|lakh)\b",
]


# ═══════════════════════════════════════════════════════════════════════
# SUPPORTING CONTEXT PATTERNS (Boost confidence when present)
# ═══════════════════════════════════════════════════════════════════════

SUPPORTING_CONTEXT_PATTERNS = {
    "has_reference_to_rules": [
        r"(?:rule|regulation|provision|guideline|circular|notification)\s+(?:no\.?|number)?\s*\d+",
        r"as\s+per\s+(?:rule|regulation|provision)",
        r"(?:GFR|FR|SR|CPWD|Manual)",
    ],
    "has_ministry_mention": [
        r"Ministry\s+of\s+[\w\s&]+",
        r"Department\s+of\s+[\w\s&]+",
        r"Government\s+of\s+[\w\s]+",
    ],
    "has_scheme_mention": [
        r"[\w\s]+(?:Scheme|Programme|Program|Mission|Yojana|Abhiyan)",
    ],
    "has_audit_reference": [
        r"para(?:graph)?\s+\d+(?:\.\d+)*",
        r"table\s+\d+(?:\.\d+)?",
        r"annexure\s+[A-Z]",
    ],
}


# ═══════════════════════════════════════════════════════════════════════
# SEMANTIC PATTERN MATCHER CLASS
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class PatternMatch:
    """Result of a pattern match."""

    category: str  # "explicit" or "implicit"
    pattern_type: str  # e.g., "audit_revealed", "variance_issue"
    matched_text: str  # The actual matched text
    base_confidence: float  # Base confidence from pattern
    description: str  # Pattern description


class SemanticPatternMatcher:
    """
    Enhanced pattern matching for CAG report semantics.

    Provides comprehensive pattern matching with confidence scoring
    to detect both explicit and implicit findings.
    """

    def __init__(self):
        """Initialize with compiled patterns."""
        # Compile explicit patterns
        self._explicit_patterns: Dict[str, List[re.Pattern]] = {}
        for pattern_type, config in EXPLICIT_PATTERNS.items():
            self._explicit_patterns[pattern_type] = [
                re.compile(p, re.IGNORECASE) for p in config["patterns"]
            ]

        # Compile implicit patterns
        self._implicit_patterns: Dict[str, List[re.Pattern]] = {}
        for pattern_type, config in IMPLICIT_PATTERNS.items():
            self._implicit_patterns[pattern_type] = [
                re.compile(p, re.IGNORECASE) for p in config["patterns"]
            ]

        # Compile monetary patterns
        self._monetary_patterns = [
            re.compile(p, re.IGNORECASE) for p in MONETARY_PATTERNS
        ]

        # Compile supporting context patterns
        self._context_patterns: Dict[str, List[re.Pattern]] = {}
        for context_type, patterns in SUPPORTING_CONTEXT_PATTERNS.items():
            self._context_patterns[context_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def match_patterns(self, text: str) -> List[PatternMatch]:
        """
        Find all pattern matches in text.

        Args:
            text: Text to analyze

        Returns:
            List of PatternMatch objects
        """
        matches = []

        # Check explicit patterns
        for pattern_type, patterns in self._explicit_patterns.items():
            for pattern in patterns:
                match_obj = pattern.search(text)
                if match_obj:
                    config = EXPLICIT_PATTERNS[pattern_type]
                    matches.append(
                        PatternMatch(
                            category="explicit",
                            pattern_type=pattern_type,
                            matched_text=match_obj.group(0),
                            base_confidence=config["confidence"],
                            description=config["description"],
                        )
                    )
                    break  # One match per type is enough

        # Check implicit patterns
        for pattern_type, patterns in self._implicit_patterns.items():
            for pattern in patterns:
                match_obj = pattern.search(text)
                if match_obj:
                    config = IMPLICIT_PATTERNS[pattern_type]
                    matches.append(
                        PatternMatch(
                            category="implicit",
                            pattern_type=pattern_type,
                            matched_text=match_obj.group(0),
                            base_confidence=config["confidence"],
                            description=config["description"],
                        )
                    )
                    break  # One match per type is enough

        return matches

    def calculate_finding_confidence(
        self,
        text: str,
        patterns_matched: List[PatternMatch],
        report_type: str = "general",
        min_text_length: int = 50,
    ) -> float:
        """
        Calculate confidence score for a potential finding.

        Combines multiple signals:
        1. Pattern match confidence (explicit > implicit)
        2. Monetary value presence
        3. Supporting context (rules, references, entities)
        4. Report type boost
        5. Text length adequacy

        Args:
            text: The text being evaluated
            patterns_matched: List of matched patterns
            report_type: Type of report (for confidence boost)
            min_text_length: Minimum text length for valid finding

        Returns:
            Float between 0.0 and 1.0
        """
        if len(text) < min_text_length:
            return 0.0

        if not patterns_matched:
            return 0.0

        # 1. Base score from pattern matches (sum capped at 0.7)
        pattern_score = min(
            sum(match.base_confidence for match in patterns_matched), 0.7
        )

        # 2. Monetary value boost (+0.2 if present)
        has_monetary = any(
            pattern.search(text) for pattern in self._monetary_patterns
        )
        monetary_boost = 0.2 if has_monetary else 0.0

        # 3. Supporting context boost (up to +0.15)
        context_boost = self._calculate_context_boost(text)

        # 4. Report type boost (multiplier)
        report_type_multiplier = report_type_profiles.get_confidence_boost(report_type)

        # 5. Text length adequacy (penalty for very short text)
        if len(text) < 100:
            length_penalty = 0.9  # 10% penalty
        else:
            length_penalty = 1.0

        # Calculate final confidence
        base_confidence = pattern_score + monetary_boost + context_boost
        final_confidence = base_confidence * report_type_multiplier * length_penalty

        return min(final_confidence, 1.0)

    def _calculate_context_boost(self, text: str) -> float:
        """
        Calculate confidence boost from supporting context.

        Returns:
            Float between 0.0 and 0.15
        """
        boost = 0.0

        if self._has_context(text, "has_reference_to_rules"):
            boost += 0.05
        if self._has_context(text, "has_ministry_mention"):
            boost += 0.03
        if self._has_context(text, "has_scheme_mention"):
            boost += 0.03
        if self._has_context(text, "has_audit_reference"):
            boost += 0.04

        return min(boost, 0.15)

    def _has_context(self, text: str, context_type: str) -> bool:
        """Check if text has a specific type of supporting context."""
        patterns = self._context_patterns.get(context_type, [])
        return any(pattern.search(text) for pattern in patterns)

    def is_finding(
        self,
        text: str,
        report_type: str = "general",
        confidence_threshold: float = 0.5,
    ) -> Tuple[bool, float, List[PatternMatch]]:
        """
        Determine if text represents a finding.

        Args:
            text: Text to evaluate
            report_type: Type of report
            confidence_threshold: Minimum confidence to consider as finding

        Returns:
            Tuple of (is_finding, confidence, patterns_matched)
        """
        patterns_matched = self.match_patterns(text)
        confidence = self.calculate_finding_confidence(text, patterns_matched, report_type)

        return (confidence >= confidence_threshold, confidence, patterns_matched)

    def get_pattern_categories(self, patterns_matched: List[PatternMatch]) -> Dict[str, int]:
        """
        Get count of matched patterns by category.

        Args:
            patterns_matched: List of matched patterns

        Returns:
            Dict with counts: {"explicit": N, "implicit": M}
        """
        categories = {"explicit": 0, "implicit": 0}
        for match in patterns_matched:
            categories[match.category] += 1
        return categories


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════


def create_matcher() -> SemanticPatternMatcher:
    """Create and return a SemanticPatternMatcher instance."""
    return SemanticPatternMatcher()


def is_finding(
    text: str,
    report_type: str = "general",
    confidence_threshold: float = 0.5,
) -> Tuple[bool, float]:
    """
    Quick check if text is a finding.

    Args:
        text: Text to evaluate
        report_type: Type of report
        confidence_threshold: Minimum confidence

    Returns:
        Tuple of (is_finding, confidence)
    """
    matcher = SemanticPatternMatcher()
    is_finding_bool, confidence, _ = matcher.is_finding(
        text, report_type, confidence_threshold
    )
    return is_finding_bool, confidence
