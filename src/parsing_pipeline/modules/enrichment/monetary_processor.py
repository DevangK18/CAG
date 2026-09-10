"""
MonetaryProcessor: Extracts and normalizes monetary values from CAG audit report text.

Handles Indian currency formats:
- ₹847.71 crore, Rs. 5,00,000, `123.45 lakh
- Normalizes all amounts to paise for precision comparisons

R2: Adds semantic context classification (FINDING_IMPACT, BUDGET_ALLOCATION, etc.)
R5: Primary amount identification for single-value reporting
"""

import re
import logging
from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


class MonetaryContext(Enum):
    """
    R2: Semantic classification of monetary amounts.

    Helps distinguish between actual audit finding impacts vs background/reference data.
    """

    FINDING_IMPACT = "finding_impact"  # Loss, shortfall, excess, irregular expenditure
    BUDGET_ALLOCATION = "budget_allocation"  # Released, allocated, sanctioned amounts
    COMPARISON_TARGET = "comparison_target"  # "Against target of ₹X"
    HISTORICAL_DATA = "historical_data"  # Multi-year totals, trend data
    EXPENDITURE_ACTUAL = "expenditure_actual"  # What was actually spent
    RECOVERY_DUE = "recovery_due"  # Amount to be recovered
    UNKNOWN = "unknown"  # Could not determine context


@dataclass
class MonetaryValue:
    """Structured representation of monetary amounts."""

    raw_text: str  # Original text: "₹847.71 crore"
    amount: float  # Numeric value: 847.71
    unit: str  # Unit: "crore", "lakh", "thousand"
    normalized_inr: int  # Normalized to INR (paise): 847710000000

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ClassifiedMonetaryValue:
    """
    R2: Monetary value with semantic context classification.

    Wraps a MonetaryValue with additional context about its role
    in the finding (impact vs background data).
    """

    value: MonetaryValue
    context: MonetaryContext = MonetaryContext.UNKNOWN
    confidence: float = 0.5  # Confidence in classification (0-1)
    is_primary: bool = False  # R5: True if this is the primary finding amount
    context_snippet: str = ""  # Text snippet that determined the context

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "value": self.value.to_dict(),
            "context": self.context.value,
            "confidence": self.confidence,
            "is_primary": self.is_primary,
            "context_snippet": self.context_snippet,
        }


class MonetaryProcessor:
    """
    Extracts and normalizes monetary values from text.

    Used by FindingExtractor to identify financial impact of audit findings.
    """

    # Pattern for Indian currency: ₹ 847.71 crore, Rs. 5,00,000, ` 123.45 lakh
    # Updated to handle Indian comma grouping (e.g., 2,41,220.26) and reject year-like patterns
    MONETARY_PATTERNS = [
        # Backtick with mandatory crore/lakh (prevents code/formatting backticks)
        r"`\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh)",
        # Standard rupee symbols with improved grouping support
        r"[₹]\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|million|billion)?",
        r"Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|million|billion)?",
        r"INR\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|million|billion)?",
        # Standalone number + unit (no symbol)
        r"([\d,]+(?:\.\d+)?)\s*(crore|lakh)\b",
    ]

    # Year-like patterns to reject (e.g., "Rs 2003", "₹2024")
    YEAR_REJECTION_PATTERN = re.compile(
        r"(?:rs|₹)\s?(?:19|20)\d{2}(?!\.\d)",
        re.IGNORECASE
    )

    # P0-01: Per-unit patterns to identify amounts that should be deprioritized
    # when an explicit total exists (e.g., "₹20,000 per beneficiary")
    PER_UNIT_PATTERN = re.compile(
        r"(?:₹|rs\.?)\s*[\d,]+(?:\.\d+)?\s*(?:crore|lakh)?\s*"
        r"(?:per|each|@)\s*(?:beneficiary|unit|person|head|month|year|day|kg|quintal|hectare|acre)",
        re.IGNORECASE
    )

    # P0-01: Explicit total patterns (e.g., "total of ₹X", "amounting to ₹X")
    EXPLICIT_TOTAL_PATTERN = re.compile(
        r"(?:total(?:ing)?|amounting|aggregat(?:ing|e)|sum(?:ming)?)\s*(?:to|of)?\s*"
        r"(?:₹|rs\.?)\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh)?",
        re.IGNORECASE
    )

    # R2: Context patterns for classifying monetary amounts
    # Each context has a list of regex patterns to match surrounding text
    CONTEXT_PATTERNS: Dict[MonetaryContext, List[re.Pattern]] = {
        MonetaryContext.FINDING_IMPACT: [
            # Loss patterns
            re.compile(
                r"(?:loss|shortfall|short[\s-]?(?:fall|recovery|collection|realization|assessment))\s+"
                r"(?:of|amounting\s+to|to\s+the\s+extent\s+of)",
                re.IGNORECASE
            ),
            # Excess/irregular patterns
            re.compile(
                r"(?:excess|irregular|avoidable|wasteful|infructuous|unfruitful|undue|unjustified)\s+"
                r"(?:expenditure|payment|advance|outgo)\s*(?:of|amounting)?",
                re.IGNORECASE
            ),
            # Result patterns
            re.compile(
                r"resulted\s+in\s+(?:a\s+)?(?:loss|extra|avoidable|wasteful|excess)",
                re.IGNORECASE
            ),
            # Non-recovery patterns
            re.compile(
                r"(?:non[\s-]?recovery|non[\s-]?realization|non[\s-]?collection|non[\s-]?realisation)\s+"
                r"(?:of|amounting)",
                re.IGNORECASE
            ),
            # Blocking/idle patterns
            re.compile(
                r"(?:blocking|locking|idle|idling)\s+(?:of\s+)?(?:funds?|amount|capital)",
                re.IGNORECASE
            ),
            # Fraud/misappropriation patterns
            re.compile(
                r"(?:fraud|misappropriation|embezzlement|suspected\s+fraud|defalcation)",
                re.IGNORECASE
            ),
            # Penalty/interest burden
            re.compile(
                r"(?:penalty|interest|damages?)\s+(?:of|amounting\s+to|to\s+the\s+tune\s+of)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.BUDGET_ALLOCATION: [
            # Released/allocated patterns
            re.compile(
                r"(?:released|allocated|sanctioned|budgeted|earmarked|provided)\s+"
                r"(?:grants?|funds?|amount|GIA|budget)",
                re.IGNORECASE
            ),
            # Passive release patterns
            re.compile(
                r"(?:grants?|funds?|GIA|budget)\s+(?:of\s+)?[₹Rs.]*[\d,]+\s*(?:crore|lakh)?\s+"
                r"(?:was|were)\s+(?:released|allocated|sanctioned)",
                re.IGNORECASE
            ),
            # Total allocation patterns
            re.compile(
                r"total\s+(?:allocation|budget|sanctioned\s+amount|outlay)",
                re.IGNORECASE
            ),
            # Government/department releases
            re.compile(
                r"(?:government|department|ministry)\s+(?:had\s+)?(?:released|allocated|sanctioned)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.COMPARISON_TARGET: [
            # Against target patterns
            re.compile(
                r"(?:against|compared\s+to|as\s+against|vis[\s-]?[aà][\s-]?vis)\s+"
                r"(?:the\s+)?(?:target|sanction|approved|budgeted|estimated)",
                re.IGNORECASE
            ),
            # Target was X patterns
            re.compile(
                r"(?:target|sanction|approved\s+cost|estimated\s+cost)\s+"
                r"(?:of|was|being)\s+[₹Rs.]*[\d,]+",
                re.IGNORECASE
            ),
            # Shortfall against patterns
            re.compile(
                r"(?:shortfall|deficit|gap)\s+(?:against|compared\s+to|vis[\s-]?[aà][\s-]?vis)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.HISTORICAL_DATA: [
            # Multi-year span patterns
            re.compile(
                r"during\s+(?:the\s+)?(?:FYs?\s+)?\d{4}[-–]\d{2,4}\s+to\s+\d{4}",
                re.IGNORECASE
            ),
            re.compile(
                r"during\s+(?:the\s+)?(?:financial\s+)?years?\s+\d{4}\s*[-–]\s*\d{4}",
                re.IGNORECASE
            ),
            re.compile(
                r"from\s+(?:FYs?\s+)?\d{4}[-–]\d{2,4}\s+to\s+\d{4}",
                re.IGNORECASE
            ),
            re.compile(
                r"(?:for|during)\s+the\s+period\s+(?:from\s+)?(?:FYs?\s+)?\d{4}",
                re.IGNORECASE
            ),
            # Over years pattern
            re.compile(
                r"over\s+(?:the\s+)?(?:last|past|previous)\s+\d+\s+(?:years?|FYs?)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.EXPENDITURE_ACTUAL: [
            # Expenditure incurred patterns
            re.compile(
                r"(?:expenditure|spending|outlay)\s+(?:incurred|made|of)",
                re.IGNORECASE
            ),
            # Amount spent patterns
            re.compile(
                r"(?:amount|funds?)\s+(?:spent|utilized|expended)",
                re.IGNORECASE
            ),
            # Actual expenditure patterns
            re.compile(
                r"actual\s+(?:expenditure|spending|cost)",
                re.IGNORECASE
            ),
        ],
        MonetaryContext.RECOVERY_DUE: [
            # Recovery due patterns
            re.compile(
                r"(?:recovery|amount)\s+(?:due|pending|recoverable|to\s+be\s+recovered)",
                re.IGNORECASE
            ),
            # Needs to be recovered patterns
            re.compile(
                r"(?:needs?|required)\s+to\s+be\s+recovered",
                re.IGNORECASE
            ),
            # Outstanding amount patterns
            re.compile(
                r"(?:outstanding|pending|recoverable)\s+(?:amount|dues?|recovery)",
                re.IGNORECASE
            ),
        ],
    }

    # Multipliers for normalization (to paise for precision)
    UNIT_MULTIPLIERS = {
        "crore": 10_000_000_00,  # 1 crore = 10^7 rupees = 10^9 paise
        "lakh": 100_000_00,  # 1 lakh = 10^5 rupees = 10^7 paise
        "thousand": 1_000_00,  # 1 thousand = 10^3 rupees = 10^5 paise
        "million": 10_000_000_00,  # 1 million ≈ 10 lakh
        "billion": 10_000_000_000_00,  # 1 billion ≈ 100 crore
        None: 100,  # Default: assume rupees, convert to paise
        "": 100,
    }

    def __init__(self):
        """Initialize with compiled regex patterns."""
        self._patterns = [
            re.compile(p, re.IGNORECASE) for p in self.MONETARY_PATTERNS
        ]

    def extract_monetary_values(self, text: str, dedup_tolerance: float = 0.05) -> List[MonetaryValue]:
        """
        Extract all monetary values from text.

        Args:
            text: Text to search for monetary values
            dedup_tolerance: Tolerance for amount-based deduplication (default 5%)

        Returns:
            List of MonetaryValue objects with normalized amounts
        """
        monetary_values = []
        seen_amounts = []  # List of (normalized_inr, unit) tuples for dedup with tolerance

        for pattern in self._patterns:
            for match in pattern.finditer(text):
                raw_text = match.group(0).strip()

                # P0-01: Reject year-like patterns (e.g., "Rs 2003", "₹2024")
                if self.YEAR_REJECTION_PATTERN.match(raw_text):
                    continue

                try:
                    # Extract amount and unit
                    groups = match.groups()
                    amount_str = groups[0].replace(",", "")
                    amount = float(amount_str)
                    unit = groups[1].lower() if len(groups) > 1 and groups[1] else None

                    # Normalize to paise
                    normalized_inr = self.normalize_to_paise(amount, unit)

                    # P0-01: Validate monetary value
                    self._validate_monetary_value(normalized_inr, raw_text)

                    # P0-01: Amount-based deduplication with tolerance
                    # Skip if we've seen a similar amount (within tolerance) with the same unit
                    is_duplicate = False
                    for seen_amount, seen_unit in seen_amounts:
                        if seen_unit == unit:
                            # Check if amounts are within tolerance (5% by default)
                            if abs(normalized_inr - seen_amount) / max(seen_amount, 1) <= dedup_tolerance:
                                is_duplicate = True
                                break

                    if is_duplicate:
                        continue

                    seen_amounts.append((normalized_inr, unit))

                    monetary_values.append(
                        MonetaryValue(
                            raw_text=raw_text,
                            amount=amount,
                            unit=unit or "rupees",
                            normalized_inr=normalized_inr,
                        )
                    )
                except (ValueError, IndexError):
                    continue

        return monetary_values

    def normalize_to_paise(self, amount: float, unit: Optional[str]) -> int:
        """
        Normalize a monetary amount to paise (1/100 of a rupee).

        Args:
            amount: Numeric amount
            unit: Unit string (crore, lakh, thousand, etc.) or None

        Returns:
            Amount in paise as integer
        """
        multiplier = self.UNIT_MULTIPLIERS.get(unit, 100)
        return int(amount * multiplier)

    def _validate_monetary_value(self, normalized_inr: int, source: str) -> None:
        """
        Validate a monetary value for correctness.

        P0-01: Unit assertions at boundaries.

        Args:
            normalized_inr: Amount in paise
            source: Source text for logging

        Raises:
            AssertionError: If value is invalid
        """
        assert isinstance(normalized_inr, int), (
            f"normalized_inr must be int, got {type(normalized_inr)}"
        )
        assert normalized_inr >= 0, (
            f"normalized_inr must be non-negative, got {normalized_inr}"
        )

        # Sanity check: ₹1 lakh crore in paise = 1e17; anything larger is suspect
        # This is ~10 times India's annual central government budget
        if normalized_inr > 1e17:
            logger.warning(
                f"Implausibly large normalized_inr={normalized_inr} from '{source}'"
            )

    def _apply_explicit_total_preference(
        self, text: str, monetary_values: List[MonetaryValue]
    ) -> List[MonetaryValue]:
        """
        P0-01: Apply explicit-total preference heuristic.

        When text contains both per-unit amounts and an explicit total,
        prefer the explicit total and filter out potentially misleading
        per-unit × count computed values.

        Heuristic:
        1. If an explicit total exists (e.g., "total of ₹X crore"), mark it as preferred
        2. If one amount is >10× another AND the larger is not an explicit total,
           and the smaller looks like a per-unit amount, keep only the explicit total
        3. Otherwise, keep all amounts

        Args:
            text: Source text
            monetary_values: List of extracted monetary values

        Returns:
            Filtered list of monetary values
        """
        if len(monetary_values) <= 1:
            return monetary_values

        # Check if there's a per-unit pattern in the text
        has_per_unit = bool(self.PER_UNIT_PATTERN.search(text))

        # Check if there's an explicit total pattern
        explicit_total_match = self.EXPLICIT_TOTAL_PATTERN.search(text)
        explicit_total_amount = None

        if explicit_total_match:
            try:
                amount_str = explicit_total_match.group(1).replace(",", "")
                amount = float(amount_str)
                unit = explicit_total_match.group(2)
                if unit:
                    unit = unit.lower()
                explicit_total_amount = self.normalize_to_paise(amount, unit)
            except (ValueError, IndexError):
                pass

        # If we have both a per-unit pattern and an explicit total,
        # prefer amounts close to the explicit total
        if has_per_unit and explicit_total_amount:
            # Find values within 10% of the explicit total
            preferred = []
            for mv in monetary_values:
                # Check if this value is close to the explicit total
                if explicit_total_amount > 0:
                    ratio = mv.normalized_inr / explicit_total_amount
                    if 0.9 <= ratio <= 1.1:
                        preferred.append(mv)
                        continue

                # Check if this is NOT a per-unit amount (doesn't have "per" in raw_text)
                if not re.search(r"\bper\b|\beach\b|@", mv.raw_text, re.IGNORECASE):
                    preferred.append(mv)

            if preferred:
                return preferred

        # Apply the 10× ratio heuristic
        # If one amount is >10× another, something might be wrong
        sorted_values = sorted(monetary_values, key=lambda x: x.normalized_inr)

        if len(sorted_values) >= 2:
            smallest = sorted_values[0].normalized_inr
            largest = sorted_values[-1].normalized_inr

            if smallest > 0 and largest / smallest > 10:
                # Large disparity - check if the larger one looks computed
                # Keep the smaller unless it's clearly a per-unit amount
                smaller_is_per_unit = bool(
                    re.search(r"\bper\b|\beach\b|@", sorted_values[0].raw_text, re.IGNORECASE)
                )

                if smaller_is_per_unit:
                    # The smaller is per-unit, keep the larger (it might be a total)
                    logger.debug(
                        f"Keeping larger amount {largest} (smaller {smallest} is per-unit)"
                    )
                else:
                    # Large disparity with no clear per-unit marker on smaller
                    # This might indicate a multiplication error - log for review
                    logger.debug(
                        f"Large monetary disparity: {smallest} vs {largest} "
                        f"(ratio: {largest/smallest:.1f}x)"
                    )

        return monetary_values

    def extract_monetary_values_with_preference(
        self, text: str, dedup_tolerance: float = 0.05
    ) -> List[MonetaryValue]:
        """
        P0-01: Extract monetary values with explicit-total preference.

        Wrapper around extract_monetary_values that applies the
        explicit-total preference heuristic.

        Args:
            text: Text to search for monetary values
            dedup_tolerance: Tolerance for amount-based deduplication (default 5%)

        Returns:
            List of MonetaryValue objects with preference applied
        """
        values = self.extract_monetary_values(text, dedup_tolerance)
        return self._apply_explicit_total_preference(text, values)

    def _classify_context(
        self, text: str, mv: MonetaryValue, window_chars: int = 150
    ) -> tuple[MonetaryContext, float, str]:
        """
        R2: Classify the semantic context of a monetary value.

        Looks for context patterns in the text surrounding the monetary value
        to determine if it's a finding impact, budget allocation, etc.

        Prioritizes patterns that directly precede the monetary value
        (e.g., "loss of ₹X" should classify the ₹X, not a different amount).

        Args:
            text: Full text containing the monetary value
            mv: The monetary value to classify
            window_chars: Number of chars before/after the value to search

        Returns:
            Tuple of (context, confidence, snippet)
        """
        # Find the position of the monetary value in the text
        try:
            pos = text.find(mv.raw_text)
        except (TypeError, ValueError):
            pos = -1

        if pos == -1:
            # Fallback: search whole intro
            search_text_before = text[:500]
            search_text_after = ""
            snippet = text[:100]
        else:
            # Get context window - separate before and after
            start = max(0, pos - window_chars)
            end = min(len(text), pos + len(mv.raw_text) + window_chars)
            search_text_before = text[start:pos]  # Text BEFORE the amount
            search_text_after = text[pos + len(mv.raw_text):end]  # Text AFTER
            snippet = text[max(0, pos - 50) : pos + len(mv.raw_text) + 50]

        # Try each context type in priority order
        # FINDING_IMPACT has highest priority (actual audit finding)
        priority_order = [
            MonetaryContext.FINDING_IMPACT,
            MonetaryContext.RECOVERY_DUE,
            MonetaryContext.COMPARISON_TARGET,
            MonetaryContext.BUDGET_ALLOCATION,
            MonetaryContext.HISTORICAL_DATA,
            MonetaryContext.EXPENDITURE_ACTUAL,
        ]

        # First pass: Look for patterns in the IMMEDIATE context before the amount
        # This ensures "loss of ₹X" associates "loss" with the ₹X that follows
        # Use a small window (50 chars) to avoid crossing into other amounts' context
        immediate_before = text[max(0, pos - 50):pos] if pos >= 0 else ""

        for context in priority_order:
            patterns = self.CONTEXT_PATTERNS.get(context, [])
            for pattern in patterns:
                # Check immediate context first (higher confidence)
                match = pattern.search(immediate_before)
                if match:
                    return context, 0.90, match.group(0)

        # Second pass: Check the broader before-window
        for context in priority_order:
            patterns = self.CONTEXT_PATTERNS.get(context, [])
            for pattern in patterns:
                match = pattern.search(search_text_before)
                if match:
                    return context, 0.75, match.group(0)

        # Third pass: Check text after the amount (lower confidence)
        for context in priority_order:
            patterns = self.CONTEXT_PATTERNS.get(context, [])
            for pattern in patterns:
                match = pattern.search(search_text_after)
                if match:
                    return context, 0.60, match.group(0)

        # No context pattern matched
        return MonetaryContext.UNKNOWN, 0.3, snippet[:50] if snippet else ""

    def extract_with_context(
        self, text: str, dedup_tolerance: float = 0.05
    ) -> List[ClassifiedMonetaryValue]:
        """
        R2: Extract monetary values with semantic context classification.

        Extracts all monetary values and classifies each by its semantic role
        (finding impact, budget allocation, historical data, etc.).

        Args:
            text: Text to search for monetary values
            dedup_tolerance: Tolerance for amount-based deduplication (default 5%)

        Returns:
            List of ClassifiedMonetaryValue objects with context
        """
        # First, extract the raw monetary values
        raw_values = self.extract_monetary_values(text, dedup_tolerance)

        if not raw_values:
            return []

        # Classify each value
        classified = []
        for mv in raw_values:
            context, confidence, snippet = self._classify_context(text, mv)
            classified.append(
                ClassifiedMonetaryValue(
                    value=mv,
                    context=context,
                    confidence=confidence,
                    is_primary=False,  # Will be set by _identify_primary
                    context_snippet=snippet,
                )
            )

        # Identify the primary amount (R5 foundation)
        self._identify_primary(classified, text)

        return classified

    def _identify_primary(
        self, classified: List[ClassifiedMonetaryValue], text: str
    ) -> None:
        """
        R5: Identify the primary finding amount.

        Marks one amount as the "primary" finding amount to use instead of
        summing all amounts. Selection priority:

        1. Explicit totals ("total of ₹X", "aggregating to ₹X")
        2. FINDING_IMPACT context amounts (highest confidence)
        3. RECOVERY_DUE amounts
        4. Maximum non-historical/non-budget amount
        5. Fallback: maximum overall amount

        Args:
            classified: List of classified monetary values (modified in-place)
            text: Full text for additional pattern matching
        """
        if not classified:
            return

        # Priority 1: Check for explicit total in text
        explicit_match = self.EXPLICIT_TOTAL_PATTERN.search(text)
        if explicit_match:
            try:
                amount_str = explicit_match.group(1).replace(",", "")
                amount = float(amount_str)
                unit = explicit_match.group(2)
                if unit:
                    unit = unit.lower()
                total_paise = self.normalize_to_paise(amount, unit)

                # Find the classified value closest to this total
                for cv in classified:
                    if total_paise > 0:
                        ratio = abs(cv.value.normalized_inr - total_paise) / total_paise
                        if ratio < 0.05:  # Within 5%
                            cv.is_primary = True
                            logger.debug(
                                f"R5: Primary amount (explicit total): {cv.value.raw_text}"
                            )
                            return
            except (ValueError, IndexError, AttributeError):
                pass

        # Priority 2: FINDING_IMPACT context with highest confidence
        finding_impacts = [
            cv for cv in classified
            if cv.context == MonetaryContext.FINDING_IMPACT
        ]
        if finding_impacts:
            # Sort by confidence (descending), then by amount (descending)
            finding_impacts.sort(
                key=lambda x: (x.confidence, x.value.normalized_inr),
                reverse=True
            )
            finding_impacts[0].is_primary = True
            logger.debug(
                f"R5: Primary amount (finding impact): {finding_impacts[0].value.raw_text}"
            )
            return

        # Priority 3: RECOVERY_DUE amounts
        recovery_due = [
            cv for cv in classified
            if cv.context == MonetaryContext.RECOVERY_DUE
        ]
        if recovery_due:
            recovery_due.sort(key=lambda x: x.value.normalized_inr, reverse=True)
            recovery_due[0].is_primary = True
            logger.debug(
                f"R5: Primary amount (recovery due): {recovery_due[0].value.raw_text}"
            )
            return

        # Priority 4: Max non-historical/non-budget amount
        eligible = [
            cv for cv in classified
            if cv.context not in (
                MonetaryContext.HISTORICAL_DATA,
                MonetaryContext.BUDGET_ALLOCATION,
            )
        ]
        if eligible:
            eligible.sort(key=lambda x: x.value.normalized_inr, reverse=True)
            eligible[0].is_primary = True
            logger.debug(
                f"R5: Primary amount (max eligible): {eligible[0].value.raw_text}"
            )
            return

        # Priority 5: Fallback - max overall
        classified.sort(key=lambda x: x.value.normalized_inr, reverse=True)
        classified[0].is_primary = True
        logger.debug(
            f"R5: Primary amount (fallback max): {classified[0].value.raw_text}"
        )

    def get_primary_amount(
        self, text: str, dedup_tolerance: float = 0.05
    ) -> Optional[ClassifiedMonetaryValue]:
        """
        R5: Extract and return only the primary monetary amount.

        Convenience method that extracts all amounts with context,
        identifies the primary, and returns just that one.

        Args:
            text: Text to search for monetary values
            dedup_tolerance: Tolerance for deduplication

        Returns:
            The primary ClassifiedMonetaryValue, or None if no amounts found
        """
        classified = self.extract_with_context(text, dedup_tolerance)
        if not classified:
            return None

        for cv in classified:
            if cv.is_primary:
                return cv

        # Shouldn't happen if _identify_primary worked, but fallback
        return classified[0] if classified else None
