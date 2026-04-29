"""
Auto-Filter Extraction for RAG Queries.

Detects implicit filter signals in queries (state names, years, tiers, audit types)
and converts them to Qdrant payload filters.

Rule-based extraction - no LLM calls required.
"""

import re
import logging
from typing import Dict, Any, Optional, List, Set

try:
    from ..core.config import AutoFilterConfig
    from .query_enhancer import QueryEnhancement
except ImportError:
    from src.core.config import AutoFilterConfig
    from query_enhancer import QueryEnhancement

logger = logging.getLogger(__name__)


# =============================================================================
# INDIAN STATES AND UTs WITH ALIASES
# =============================================================================

INDIAN_STATES_WITH_ALIASES: Dict[str, List[str]] = {
    # States (28)
    "Andhra Pradesh": ["andhra pradesh", "ap", "andhra"],
    "Arunachal Pradesh": ["arunachal pradesh", "arunachal"],
    "Assam": ["assam"],
    "Bihar": ["bihar"],
    "Chhattisgarh": ["chhattisgarh", "chattisgarh"],
    "Goa": ["goa"],
    "Gujarat": ["gujarat"],
    "Haryana": ["haryana"],
    "Himachal Pradesh": ["himachal pradesh", "himachal", "hp"],
    "Jharkhand": ["jharkhand"],
    "Karnataka": ["karnataka"],
    "Kerala": ["kerala"],
    "Madhya Pradesh": ["madhya pradesh", "mp"],
    "Maharashtra": ["maharashtra"],
    "Manipur": ["manipur"],
    "Meghalaya": ["meghalaya"],
    "Mizoram": ["mizoram"],
    "Nagaland": ["nagaland"],
    "Odisha": ["odisha", "orissa"],
    "Punjab": ["punjab"],
    "Rajasthan": ["rajasthan"],
    "Sikkim": ["sikkim"],
    "Tamil Nadu": ["tamil nadu", "tamilnadu", "tn"],
    "Telangana": ["telangana"],
    "Tripura": ["tripura"],
    "Uttar Pradesh": ["uttar pradesh", "up"],
    "Uttarakhand": ["uttarakhand", "uttaranchal"],
    "West Bengal": ["west bengal", "wb"],
    # Union Territories (8)
    "Andaman and Nicobar Islands": ["andaman", "nicobar", "andaman and nicobar"],
    "Chandigarh": ["chandigarh"],
    "Dadra and Nagar Haveli and Daman and Diu": ["dadra", "daman", "diu", "dadra and nagar haveli", "daman and diu"],
    "Delhi": ["delhi", "ncr", "nct"],
    "Jammu and Kashmir": ["jammu", "kashmir", "jammu and kashmir", "j&k", "jk"],
    "Ladakh": ["ladakh"],
    "Lakshadweep": ["lakshadweep"],
    "Puducherry": ["puducherry", "pondicherry"],
}

# These aliases are common English words/abbreviations and require extra confidence
# (≥2 occurrences OR explicit context cue) before triggering a state filter
SHORT_AMBIGUOUS_ALIASES = {
    "ap", "hp", "mp", "tn", "up", "wb", "jk", "j&k",
    "andhra",  # also somewhat ambiguous
    "ncr", "nct",  # Delhi NCR/NCT are real but rarely useful as filters
}

# Build reverse lookup: alias -> canonical state name
ALIAS_TO_STATE: Dict[str, str] = {}
for canonical, aliases in INDIAN_STATES_WITH_ALIASES.items():
    for alias in aliases:
        ALIAS_TO_STATE[alias.lower()] = canonical


# =============================================================================
# TIER KEYWORDS
# =============================================================================

UNION_KEYWORDS: Set[str] = {
    "union government",
    "central government",
    "government of india",
    "goi",
    "ministry of",
    "central scheme",
    "central ministry",
    "union ministry",
    "centrally sponsored",
    "central sector",
    "union audit",
    "central audit",
}

LOCAL_BODY_KEYWORDS: Set[str] = {
    "panchayat",
    "panchayati raj",
    "pri",
    "ulb",
    "urban local body",
    "urban local bodies",
    "municipal",
    "municipality",
    "municipal corporation",
    "village council",
    "gram panchayat",
    "gram sabha",
    "zila parishad",
    "block development",
    "local body",
    "local bodies",
    "local fund",
    "atir",
    "annual technical inspection",
}


# =============================================================================
# AUDIT CATEGORY KEYWORDS
# =============================================================================

AUDIT_CATEGORY_KEYWORDS: Dict[str, Set[str]] = {
    "performance": {
        "performance audit",
        "performance review",
        "performance evaluation",
        "outcome audit",
    },
    "compliance": {
        "compliance audit",
        "compliance review",
        "regulatory compliance",
        "transaction audit",
    },
    "financial": {
        "financial audit",
        "financial attest",
        "finance accounts",
        "appropriation audit",
        "frbm",
        "fiscal responsibility",
    },
    "revenue": {
        "revenue audit",
        "revenue receipts",
        "tax audit",
        "gst audit",
    },
    "commercial": {
        "commercial audit",
        "psu audit",
        "public sector undertaking",
        "state pse",
        "spse",
    },
    "atir": {
        "atir",
        "annual technical inspection",
        "local fund audit",
    },
}


# =============================================================================
# STATE CONTEXT CUES (for confidence)
# =============================================================================

STATE_CONTEXT_CUES: Set[str] = {
    "in",
    "of",
    "from",
    "government of",
    "state of",
    "state",
    "government",
    "ag",
    "accountant general",
}


# =============================================================================
# AUTO FILTER EXTRACTOR
# =============================================================================


class AutoFilterExtractor:
    """
    Extracts implicit filters from query text using rule-based detection.

    Detects:
    - Years (single → audit_year, range → report_year)
    - State names (with tier inference)
    - Tier keywords (union, state, local_body)
    - Audit category keywords

    Also pulls suggested_filters from QueryEnhancement for finding_type/severity.
    """

    def __init__(self, config: AutoFilterConfig):
        self.config = config
        self._year_pattern = re.compile(r'\b(20\d{2})\b')

    def extract(
        self,
        query: str,
        query_enhancement: Optional[QueryEnhancement] = None,
    ) -> Dict[str, Any]:
        """
        Extract auto-filters from query text.

        Args:
            query: The user's question
            query_enhancement: Optional QueryEnhancement with suggested_filters

        Returns:
            Dict of filter key-value pairs (never None, may be empty)
        """
        if not self.config.enabled:
            return {}

        filters: Dict[str, Any] = {}
        query_lower = query.lower()

        # 1. Extract years
        if self.config.allow_year_inference:
            year_filters = self._extract_years(query)
            filters.update(year_filters)

        # 2. Extract state (also sets tier to "state")
        state_name = self._extract_state(query_lower)
        if state_name:
            filters["state_name"] = state_name
            filters["government_body_type"] = "state"

        # 3. Extract tier keywords (only if state didn't already set it)
        if self.config.allow_tier_inference and "government_body_type" not in filters:
            tier = self._extract_tier(query_lower)
            if tier:
                filters["government_body_type"] = tier

        # 4. Extract audit category
        category = self._extract_audit_category(query_lower)
        if category:
            filters["audit_category"] = category

        # 5. Pull from QueryEnhancement.suggested_filters (finding_type, severity)
        if query_enhancement and query_enhancement.suggested_filters:
            for key, value in query_enhancement.suggested_filters.items():
                if key not in filters:
                    filters[key] = value

        if filters:
            logger.info(f"Auto-extracted filters: {filters}")

        return filters

    def _extract_years(self, query: str) -> Dict[str, Any]:
        """
        Extract year filters from query.

        - Single year → audit_year as "YYYY-YY+1"
        - Multiple years → report_year as range
        """
        matches = self._year_pattern.findall(query)
        if not matches:
            return {}

        years = sorted(set(int(y) for y in matches))

        if len(years) == 1:
            # Single year → convert to audit_year format
            year = years[0]
            next_year_suffix = str((year + 1) % 100).zfill(2)
            audit_year = f"{year}-{next_year_suffix}"
            return {"audit_year": audit_year}
        else:
            # Multiple years → range filter
            return {"report_year": {"gte": min(years), "lte": max(years)}}

    def _extract_state(self, query_lower: str) -> Optional[str]:
        """
        Extract state name from query with confidence guard.

        Requires either:
        - State appears with context cue (e.g., "in Kerala", "Government of Kerala")
        - State appears ≥ config.state_confidence_min_occurrences times
        - For ambiguous aliases (UP, MP, TN, etc.): requires ≥2 occurrences OR context cue
        """
        found_states: Dict[str, int] = {}  # canonical_name -> count
        has_non_ambiguous_match: Dict[str, bool] = {}  # canonical_name -> has non-ambiguous alias

        for alias, canonical in ALIAS_TO_STATE.items():
            # Count occurrences of this alias
            count = len(re.findall(rf'\b{re.escape(alias)}\b', query_lower))
            if count > 0:
                found_states[canonical] = found_states.get(canonical, 0) + count
                # Track if this state has at least one non-ambiguous alias match
                if alias not in SHORT_AMBIGUOUS_ALIASES:
                    has_non_ambiguous_match[canonical] = True

        if not found_states:
            return None

        # Pick the most frequently mentioned state
        best_state = max(found_states, key=lambda s: found_states[s])
        occurrence_count = found_states[best_state]

        # Check if best_state was matched ONLY via ambiguous aliases
        matched_only_ambiguous = best_state not in has_non_ambiguous_match

        # Confidence guard for ambiguous-only matches
        if matched_only_ambiguous:
            # Require ≥2 occurrences OR a context cue
            if occurrence_count < 2:
                # Must have a context cue to proceed
                has_context_cue = False
                for alias in INDIAN_STATES_WITH_ALIASES[best_state]:
                    for cue in STATE_CONTEXT_CUES:
                        patterns = [
                            rf'\b{re.escape(cue)}\s+{re.escape(alias)}\b',
                            rf'\b{re.escape(alias)}\s+{re.escape(cue)}\b',
                        ]
                        for pattern in patterns:
                            if re.search(pattern, query_lower):
                                has_context_cue = True
                                break
                        if has_context_cue:
                            break
                    if has_context_cue:
                        break

                if not has_context_cue:
                    return None
            # If occurrence_count >= 2, proceed with the match
            return best_state

        # For non-ambiguous matches, use original confidence logic
        if occurrence_count >= self.config.state_confidence_min_occurrences:
            return best_state

        # Check for context cues around the state mention
        for alias in INDIAN_STATES_WITH_ALIASES[best_state]:
            for cue in STATE_CONTEXT_CUES:
                # Pattern: "in Kerala", "of Kerala", "Kerala state", etc.
                patterns = [
                    rf'\b{re.escape(cue)}\s+{re.escape(alias)}\b',
                    rf'\b{re.escape(alias)}\s+{re.escape(cue)}\b',
                ]
                for pattern in patterns:
                    if re.search(pattern, query_lower):
                        return best_state

        return None

    def _extract_tier(self, query_lower: str) -> Optional[str]:
        """Extract government tier from keywords."""
        # Check union keywords
        for kw in UNION_KEYWORDS:
            if kw in query_lower:
                return "union"

        # Check local body keywords
        for kw in LOCAL_BODY_KEYWORDS:
            if kw in query_lower:
                return "local_body"

        return None

    def _extract_audit_category(self, query_lower: str) -> Optional[str]:
        """Extract audit category from keywords."""
        for category, keywords in AUDIT_CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in query_lower:
                    return category
        return None


# =============================================================================
# VERIFICATION / TESTING
# =============================================================================

if __name__ == "__main__":
    print("Testing AutoFilterExtractor with ambiguous alias guards...")
    print("=" * 70)

    ext = AutoFilterExtractor(AutoFilterConfig())

    # Test cases that should NOT match (false positives previously)
    false_positive_tests = [
        ("What was the audit process up to 2023?", "up as preposition"),
        ("How important is TN audit reports?", "TN as unrelated acronym"),
        ("MP welfare scheme audit findings", "MP could be Member of Parliament"),
        ("compliance with implementation procedures", "with/implementation don't match states"),
    ]

    print("\n1. FALSE POSITIVE PREVENTION (should NOT extract state):")
    print("-" * 70)
    for query, description in false_positive_tests:
        result = ext.extract(query)
        has_state = "state_name" in result
        status = "❌ FAIL" if has_state else "✅ PASS"
        print(f"{status} | {description}")
        print(f"      Query: '{query}'")
        if has_state:
            print(f"      ERROR: Extracted state_name={result['state_name']}")
        print()

    # Test cases that should still match (high-confidence cases)
    true_positive_tests = [
        ("Government of UP findings", "Uttar Pradesh", "context cue: 'Government of'"),
        ("audit of Kerala", "Kerala", "context cue: 'of' + non-ambiguous name"),
        ("UP and UP again, UP to 2023", "Uttar Pradesh", "≥2 occurrences of UP"),
        ("Tamil Nadu schemes", "Tamil Nadu", "non-ambiguous full name"),
        ("findings in Maharashtra", "Maharashtra", "non-ambiguous with context"),
        ("State of HP audit", "Himachal Pradesh", "context cue: 'State of'"),
    ]

    print("\n2. TRUE POSITIVE PRESERVATION (should extract state correctly):")
    print("-" * 70)
    for query, expected_state, description in true_positive_tests:
        result = ext.extract(query)
        actual_state = result.get("state_name")
        matches = actual_state == expected_state
        status = "✅ PASS" if matches else "❌ FAIL"
        print(f"{status} | {description}")
        print(f"      Query: '{query}'")
        print(f"      Expected: {expected_state}, Got: {actual_state}")
        print()

    print("=" * 70)
    print("Short ambiguous alias guards verification complete!")
