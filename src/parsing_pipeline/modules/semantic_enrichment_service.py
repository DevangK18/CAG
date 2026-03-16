"""
SemanticEnrichmentService: CAG-specific semantic tagging and entity extraction.

PHASE 5 IMPLEMENTATION + PHASE 1 P1-1 ENHANCEMENT (Report Type Adaptation)

Extracts structured data from CAG audit reports:
1. Findings - Audit observations with monetary values and severity
2. Recommendations - Action items for ministries/departments
3. Section Types - Semantic classification of document sections
4. Monetary Aggregates - Total amounts by category
5. Key Entities - Ministries, schemes, programs mentioned

PHASE 1 ENHANCEMENTS:
- P1-1: Report-type aware extraction using type-specific patterns
- Detects report type (Compliance, Performance, Financial)
- Applies type-specific finding patterns for better coverage

This structured data enables cross-report analytics queries like:
- "Top 10 largest irregular expenditures across all reports"
- "Which ministry has the most pending recommendations?"
- "Compare audit findings in Railways 2023 vs 2024"
"""

import re
import hashlib
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

# P1-1: Import report type profiles
from src.parsing_pipeline.modules import report_type_profiles
from src.core.data_contracts import DocumentTask

# P1-2: Import enhanced semantic patterns
from src.parsing_pipeline.modules import semantic_patterns

# P1-3: Import evidence linker
from src.parsing_pipeline.modules import evidence_linker

# P3-3: Import temporal extractor
from src.parsing_pipeline.modules.enrichment.temporal_extractor import TemporalExtractor

# P3-5: Import annexure linker
from src.parsing_pipeline.modules.enrichment.annexure_linker import AnnexureLinker

# P3-6: Import cross-reference resolver
from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import CrossReferenceResolver

# Import data contracts for Recommendation
from src.core.data_contracts import (
    Recommendation,
    Finding,
    SectionClassification,
    SemanticEnrichment,
)


class FindingType(Enum):
    """Classification of audit finding types."""

    IRREGULAR_EXPENDITURE = "irregular_expenditure"
    LOSS_OF_REVENUE = "loss_of_revenue"
    WASTEFUL_EXPENDITURE = "wasteful_expenditure"
    NON_COMPLIANCE = "non_compliance"
    SYSTEM_DEFICIENCY = "system_deficiency"
    PERFORMANCE_SHORTFALL = "performance_shortfall"
    FRAUD_MISAPPROPRIATION = "fraud_misappropriation"
    PROCEDURAL_LAPSE = "procedural_lapse"
    # State/Local Body finding types
    IDLE_ASSETS = "idle_assets"
    NON_REALIZATION_OF_DUES = "non_realization_of_dues"
    INCOMPLETE_INFRASTRUCTURE = "incomplete_infrastructure"
    ACCOUNTING_IRREGULARITY = "accounting_irregularity"
    FUND_UTILIZATION_FAILURE = "fund_utilization_failure"
    OTHER = "other"


class Severity(Enum):
    """Severity classification based on monetary value and impact."""

    CRITICAL = "critical"  # > ₹100 crore or systemic issues
    HIGH = "high"  # ₹10-100 crore or significant impact
    MEDIUM = "medium"  # ₹1-10 crore or moderate impact
    LOW = "low"  # < ₹1 crore or minor issues


class SectionType(Enum):
    """Semantic classification of document sections."""

    EXECUTIVE_SUMMARY = "executive_summary"
    INTRODUCTION = "introduction"
    AUDIT_OBJECTIVES = "audit_objectives"
    AUDIT_SCOPE = "audit_scope"
    AUDIT_METHODOLOGY = "audit_methodology"
    AUDIT_CRITERIA = "audit_criteria"
    FINDINGS = "findings"
    RECOMMENDATIONS = "recommendations"
    CONCLUSION = "conclusion"
    ANNEXURE = "annexure"
    GLOSSARY = "glossary"
    ACKNOWLEDGEMENT = "acknowledgement"
    PREFACE = "preface"
    OTHER = "other"


@dataclass
class MonetaryValue:
    """Structured representation of monetary amounts."""

    raw_text: str  # Original text: "₹847.71 crore"
    amount: float  # Numeric value: 847.71
    unit: str  # Unit: "crore", "lakh", "thousand"
    normalized_inr: int  # Normalized to INR (paise): 847710000000

    def to_dict(self) -> Dict:
        return asdict(self)


# NOTE: Finding, Recommendation, SectionClassification, and SemanticEnrichment
# are now imported from src.core.data_contracts (see imports above)


class SemanticEnrichmentService:
    """
    Enriches parsed CAG documents with semantic tags and extracted entities.

    Key Capabilities:
    1. Finding Extraction - Identifies audit observations with monetary impact
    2. Recommendation Extraction - Extracts action items for ministries
    3. Section Classification - Tags sections by semantic type
    4. Monetary Normalization - Converts all amounts to comparable INR values
    5. Entity Extraction - Identifies schemes, programs, ministries mentioned
    """

    # ==================== MONETARY PATTERNS ====================

    # Pattern for Indian currency: ₹ 847.71 crore, Rs. 5,00,000, ` 123.45 lakh
    MONETARY_PATTERNS = [
        # Backtick with mandatory crore/lakh (prevents code/formatting backticks)
        r"`\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh)",
        # Standard rupee symbols
        r"[₹]\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|million|billion)?",
        r"Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|million|billion)?",
        r"INR\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|thousand|million|billion)?",
        # Standalone number + unit (no symbol)
        r"([\d,]+(?:\.\d+)?)\s*(crore|lakh)\b",
    ]

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

    # ==================== SEVERITY THRESHOLDS (Tier-Specific) ====================

    # Tier-specific severity thresholds in crore
    # State/Local Body amounts are structurally smaller than Union amounts
    SEVERITY_THRESHOLDS = {
        "union": {"critical": 100, "high": 10, "medium": 1, "low": 0},  # Rs crore
        "state": {"critical": 50, "high": 5, "medium": 0.5, "low": 0},  # Rs crore
        "local_body": {"critical": 10, "high": 1, "medium": 0.10, "low": 0},  # Rs crore (10 lakh = 0.10 crore)
    }

    # ==================== FINDING PATTERNS ====================

    FINDING_TYPE_PATTERNS = {
        FindingType.IRREGULAR_EXPENDITURE: [
            r"irregular\s+expenditure",
            r"irregularly\s+(spent|incurred|paid)",
            r"unauthorized\s+expenditure",
            r"expenditure\s+not\s+sanctioned",
        ],
        FindingType.LOSS_OF_REVENUE: [
            r"loss\s+of\s+revenue",
            r"revenue\s+loss",
            r"short\s+(levy|collection|realization)",
            r"non-?recovery\s+of",
            r"tax\s+evasion",
        ],
        FindingType.WASTEFUL_EXPENDITURE: [
            r"wasteful\s+expenditure",
            r"infructuous\s+expenditure",
            r"unfruitful\s+expenditure",
            r"idle\s+(investment|expenditure|machinery|equipment)",
            r"blocking\s+of\s+funds",
        ],
        FindingType.NON_COMPLIANCE: [
            r"non-?compliance",
            r"violation\s+of",
            r"contrary\s+to\s+(rules|guidelines|provisions)",
            r"in\s+contravention\s+of",
            r"failed\s+to\s+comply",
        ],
        FindingType.SYSTEM_DEFICIENCY: [
            r"system(ic)?\s+deficien",
            r"internal\s+control\s+(weakness|deficiency)",
            r"lack\s+of\s+(monitoring|oversight|control)",
            r"absence\s+of\s+(mechanism|system|procedure)",
        ],
        FindingType.PERFORMANCE_SHORTFALL: [
            r"performance\s+(shortfall|gap|deficiency)",
            r"target\s+not\s+(achieved|met)",
            r"underperformance",
            r"below\s+(target|benchmark|standard)",
            r"delay\s+in\s+(completion|implementation|execution)",
        ],
        FindingType.FRAUD_MISAPPROPRIATION: [
            r"fraud",
            r"misappropriation",
            r"embezzlement",
            r"fictitious",
            r"bogus\s+(claim|bill|payment)",
        ],
        FindingType.PROCEDURAL_LAPSE: [
            r"procedural\s+(lapse|irregularity|deviation)",
            r"without\s+(approval|sanction|authorization)",
            r"non-?adherence\s+to\s+(procedure|norm|guideline)",
        ],
        FindingType.IDLE_ASSETS: [
            r"lying\s+idle\s+for\s+\d+\s+(?:months?|years?)",
            r"not\s+put\s+to\s+(?:use|productive\s+use)",
            r"not\s+made\s+operational",
            r"low\s+occupancy",
            r"poor\s+occupancy",
            r"remained\s+non-?functional",
            r"assets?\s+created\s+(?:were|was)\s+not\s+util[iz]ed",
            r"not\s+been\s+put\s+to\s+use",
            r"properties?\s+lying\s+idle",
            r"equipment\s+lying\s+idle",
            r"remained\s+idle",
            r"remained\s+unutili[sz]ed",
            r"lying\s+unused",
        ],
        FindingType.NON_REALIZATION_OF_DUES: [
            r"non-?reali[sz]ation\s+of\s+dues",
            r"non-?recovery\s+of\s+dues",
            r"non-?collection\s+of\s+dues",
            r"non-?reali[sz]ation\s+of\s+rent",
            r"non-?recovery\s+of\s+revenue",
            r"non-?collection\s+of\s+revenue",
            r"outstanding\s+dues\s+amounting\s+to",
            r"unreali[sz]ed\s+dues",
            r"unrecovered\s+dues",
            r"dues\s+remained\s+unreali[sz]ed",
            r"dues\s+remained\s+unrecovered",
            r"arrears\s+of\s+revenue",
            r"arrears\s+amounting\s+to",
        ],
        FindingType.INCOMPLETE_INFRASTRUCTURE: [
            r"work\s+was\s+(?:stopped|stalled|abandoned)",
            r"could\s+not\s+be\s+completed",
            r"remained\s+incomplete",
            r"not\s+yet\s+completed",
            r"only\s+\d+%?\s+of\s+work\s+(?:executed|completed)",
            r"balance\s+works?\s+not\s+(?:taken\s+up|completed)",
            r"project\s+remained\s+incomplete",
            r"construction\s+remained\s+incomplete",
            r"inordinate\s+delay\s+in\s+completion",
            r"time\s+overrun",
            r"cost\s+overrun",
        ],
        FindingType.ACCOUNTING_IRREGULARITY: [
            r"accounts?\s+not\s+(?:maintained|prepared|finali[sz]ed)",
            r"non-?reconciliation\s+of",
            r"unreconciled\s+balances?",
            r"differences?\s+in\s+balances?",
            r"PRIASoft\s+not\s+(?:maintained|updated|implemented)",
            r"non-?submission\s+of\s+utili[sz]ation\s+certificates?",
            r"UCs?\s+not\s+submitted",
            r"UCs?\s+pending",
            r"discrepanc(?:y|ies)\s+in\s+(?:figures?|records?|accounts?|books?|balances?)",
            r"non-?preparation\s+of\s+(?:accounts?|annual\s+accounts?|balance\s+sheet)",
            r"cash\s+book\s+not\s+maintained",
            r"stock\s+register\s+not\s+maintained",
        ],
        FindingType.FUND_UTILIZATION_FAILURE: [
            r"funds?\s+remained\s+(?:unspent|unutili[sz]ed)",
            r"non-?release\s+of\s+funds?",
            r"non-?utili[sz]ation\s+of\s+funds?",
            r"blocking\s+of\s+funds?",
            r"Finance\s+Commission\s+funds?\s+(?:unspent|unutili[sz]ed|blocked|not\s+released)",
            r"grants?\s+remained\s+unutili[sz]ed",
            r"grants?\s+not\s+released",
            r"funds?\s+(?:were|was)\s+not\s+utili[sz]ed",
            r"funds?\s+could\s+not\s+be\s+utili[sz]ed",
            r"short\s+release\s+of\s+(?:funds?|grants?)",
            r"delayed\s+release\s+of\s+(?:funds?|grants?)",
        ],
    }

    # ==================== RECOMMENDATION PATTERNS ====================

    RECOMMENDATION_PATTERNS = [
        # Direct recommendations
        r"(?:We\s+)?recommend(?:ed)?\s+that\s+(.+?)(?:\.|$)",
        r"Recommendation\s*[:\-–]\s*(.+?)(?:\.|$)",
        r"Audit\s+recommend(?:s|ed)\s+that\s+(.+?)(?:\.|$)",
        # Should/may patterns
        r"(?:The\s+)?Ministry\s+should\s+(.+?)(?:\.|$)",
        r"(?:The\s+)?Department\s+should\s+(.+?)(?:\.|$)",
        r"(?:The\s+)?Government\s+should\s+(.+?)(?:\.|$)",
        r"(?:The\s+)?Railways\s+should\s+(.+?)(?:\.|$)",
        # Needs to / required to patterns
        r"(?:The\s+)?Ministry\s+(?:needs|is\s+required)\s+to\s+(.+?)(?:\.|$)",
        r"(?:The\s+)?Department\s+(?:needs|is\s+required)\s+to\s+(.+?)(?:\.|$)",
        # May consider patterns
        r"(?:The\s+)?Ministry\s+may\s+consider\s+(.+?)(?:\.|$)",
        r"(?:The\s+)?Department\s+may\s+consider\s+(.+?)(?:\.|$)",
        # It is suggested patterns
        r"It\s+is\s+(?:suggested|recommended)\s+that\s+(.+?)(?:\.|$)",
        # ATIR-specific patterns (State/Local Body reports)
        r"State\s+Government\s+(?:needs\s+to|should|must|may\s+ensure|may\s+take|may\s+strengthen)\s+(.+?)(?:\.|$)",
        r"It\s+is\s+(?:imperative|necessary|essential)\s+that\s+(.+?)(?:\.|$)",
        r"It\s+is\s+recommended\s+that\s+(.+?)(?:\.|$)",
        r"PRIs\s+(?:should|must|need\s+to)\s+(.+?)(?:\.|$)",
        r"ULBs\s+(?:should|must|need\s+to)\s+(.+?)(?:\.|$)",
        r"Gram\s+Panchayats?\s+(?:should|must|need\s+to)\s+(.+?)(?:\.|$)",
        r"Government\s+(?:should|needs\s+to|must)\s+ensure\s+(.+?)(?:\.|$)",
        r"expedite\s+the\s+(?:preparation|submission|finali[sz]ation|reconciliation)\s+(.+?)(?:\.|$)",
    ]

    # Target entity extraction from recommendations
    TARGET_ENTITY_PATTERNS = [
        r"(Ministry\s+of\s+[\w\s&]+?)(?:\s+should|\s+may|\s+needs)",
        r"(Department\s+of\s+[\w\s&]+?)(?:\s+should|\s+may|\s+needs)",
        r"(Government\s+of\s+[\w\s]+?)(?:\s+should|\s+may|\s+needs)",
        r"(Indian\s+Railways?)(?:\s+should|\s+may|\s+needs)",
        r"(Railway\s+Board)(?:\s+should|\s+may|\s+needs)",
    ]

    # ==================== SECTION TYPE PATTERNS ====================

    SECTION_TYPE_PATTERNS = {
        SectionType.EXECUTIVE_SUMMARY: [
            r"^executive\s+summary",
            r"^highlights",
            r"^overview",
            r"^key\s+findings",
        ],
        SectionType.INTRODUCTION: [
            r"^introduction",
            r"^chapter\s+[i1][\s:]+introduction",
            r"^background",
        ],
        SectionType.AUDIT_OBJECTIVES: [
            r"audit\s+objective",
            r"objective(?:s)?\s+of\s+(?:the\s+)?audit",
        ],
        SectionType.AUDIT_SCOPE: [
            r"scope\s+of\s+audit",
            r"audit\s+scope",
            r"scope\s+and\s+coverage",
        ],
        SectionType.AUDIT_METHODOLOGY: [
            r"audit\s+methodology",
            r"methodology",
            r"audit\s+approach",
        ],
        SectionType.AUDIT_CRITERIA: [
            r"audit\s+criteria",
            r"criteria\s+for\s+audit",
            r"sources\s+of\s+audit\s+criteria",
        ],
        SectionType.FINDINGS: [
            r"audit\s+findings",
            r"detailed\s+findings",
            r"chapter\s+[iIvV234]+[\s:]+audit\s+findings",
            r"observations",
        ],
        SectionType.RECOMMENDATIONS: [
            r"^recommendations",
            r"audit\s+recommendations",
            r"summary\s+of\s+recommendations",
        ],
        SectionType.CONCLUSION: [
            r"^conclusion",
            r"^concluding\s+remarks",
            r"^summary\s+and\s+conclusion",
        ],
        SectionType.ANNEXURE: [
            r"^annexure",
            r"^appendix",
            r"^annex\s+",
        ],
        SectionType.GLOSSARY: [
            r"^glossary",
            r"^abbreviations",
            r"^list\s+of\s+abbreviations",
        ],
        SectionType.ACKNOWLEDGEMENT: [
            r"^acknowledgement",
            r"^preface",
        ],
    }

    # ==================== ENTITY PATTERNS ====================

    # P3-1: Enhanced ENTITY_PATTERNS with stricter matching
    ENTITY_PATTERNS = {
        "schemes": [
            # Require capital letter start, cap at 60 chars
            # Use non-capturing groups for context words (the, under)
            r"(?:[Uu]nder\s+)?(?:the\s+)?([A-Z][\w\s]{2,55}(?:Scheme|Programme|Program|Mission|Yojana|Abhiyan))",
            r"(?:[Uu]nder\s+)?(?:the\s+)?([A-Z][\w\s]{2,55}(?:Scheme|Programme|Program|Mission|Yojana))",
            # Explicit acronym-in-parens pattern: "Pradhan Mantri Gram Sadak Yojana (PMGSY)"
            r"(?:[Uu]nder\s+)?(?:the\s+)?([A-Z][\w\s]{5,55})\s*\([A-Z]{2,8}\)",
        ],
        "ministries": [
            # Match Ministry/Department of <Capitalized Words>
            # Stop before "and Ministry/Department" (separate entity)
            # Allow internal "and" for names like "Micro, Small & Medium Enterprises"
            r"(Ministry\s+of\s+[A-Z][a-z\w]*(?:(?:,\s*|\s+&\s+|\s+)[A-Z](?!inistry|epartment)[a-z\w]*){0,5})",
            r"(Department\s+of\s+[A-Z][a-z\w]*(?:(?:,\s*|\s+&\s+|\s+)[A-Z](?!inistry|epartment)[a-z\w]*){0,5})",
        ],
        "organizations": [
            r"((?:Indian\s+)?Railways?)",
            # Common CAG acronyms
            r"(INCOIS|ISRO|DRDO|CPWD|PWD|NHAI|ONGC|BHEL|SAIL|HAL|AAI|FCI)",
            # State PSEs
            r"(\w+\s+(?:Tourism|Power|Finance|Mining|Transport|Industrial)\s+Corporation)",
            # State boards
            r"(\w+\s+(?:Electricity|Pollution\s+Control|Revenue)\s+(?:Board|Commission))",
            # State government abbreviations
            r"\b(Go(?:AP|HP|SK|UK|OD|MH|KL|AS|BR|CG))\b",
            # PRIs (Panchayati Raj Institutions)
            r"(Gram\s+Panchayats?)",
            r"(Zilla\s+Panchayats?)",
            r"(Zila\s+Parishads?)",
            r"(Panchayat\s+Samitis?)",
            r"(Block\s+Panchayats?)",
            # ULBs (Urban Local Bodies)
            r"(Municipal\s+Corporations?)",
            r"(Municipal\s+Councils?)",
            r"(Nagar\s+Panchayats?)",
            r"(Nagar\s+Palikas?)",
            r"(Nagar\s+Nigams?)",
            # Local positions (treated as organizations)
            r"(Block\s+Development\s+Officers?)",
            r"(District\s+Programme\s+Coordinators?)",
            r"(Adhyakshas?)",
            r"(Sarpanchs?)",
            # Finance Commission
            r"(\d+th\s+(?:Central|State)\s+Finance\s+Commission)",
            # Require 2+ capitalized words before suffix, max 60 chars
            r"((?:[A-Z][a-z]+\s+){1,5}(?:Corporation|Authority|Board|Commission|Council))",
        ],
    }

    # P3-1: Verb stems and prepositions that indicate captured sentence fragments, not entities
    ENTITY_REJECT_VERBS = {
        "was", "were", "is", "are", "has", "had", "have", "been",
        "said", "noted", "observed", "stated", "found", "reported",
        "recommended", "suggested", "directed", "instructed",
        "mentioned", "indicated", "revealed", "submitted",
        "failed", "did", "does", "could", "should", "would",
        "the", "that", "this", "which", "where", "when",
        "under", "over", "during", "after", "before", "from",  # Prepositions
    }

    # ==================== P4-2: BOX ELEMENT PATTERNS ====================

    # Only match explicit "Box X.X" labels — NOT colored-background sections
    BOX_CAPTION_PATTERNS = [
        # "Box 3.1: Illustration of excess expenditure"
        r"(Box\s+\d+(?:\.\d+)?)\s*[:\-–]\s*(.+?)(?:\.|$)",
        # "Box 3.1 Illustration of ..." (no colon)
        r"(Box\s+\d+(?:\.\d+)?)\s+([A-Z].+?)(?:\.|$)",
        # "Box-1: ..." (some reports use hyphen)
        r"(Box[-\s]+\d+(?:\.\d+)?)\s*[:\-–]\s*(.+?)(?:\.|$)",
    ]

    # Subtype classification for box content
    BOX_SUBTYPE_KEYWORDS = {
        "illustration": ["illustration", "illustrat", "example", "case study", "instance"],
        "calculation": ["calculation", "computation", "working", "formula"],
        "case_study": ["case study", "case of", "specific case"],
        "summary": ["summary", "gist", "brief", "snapshot"],
        "comparison": ["comparison", "comparative", "vis-a-vis", "versus"],
    }

    # ==================== SCHEME REJECTION PATTERNS ====================

    # Scheme rejection patterns (filter out false positives)
    SCHEME_REJECT_PATTERNS = [
        r"^As\s+per\s+",
        r"^Audit\s+(?:noticed|observed|conducted|of\s+Scheme)",
        r"^In\s+(?:respect\s+of|the|STO|Municipal)",
        r"^It\s+was\s+",
        r"^A\s+total\s+of\s+\d+",
        r"^A\s+has\s+",
        r"^An\s+Audit",
        r"^(?:Section|Rule|Clause)\s+\d+",
        r"DLFA\s+also",
        r"Local\s+Fund\s+Accounts\s+Audit",
    ]

    def __init__(self):
        """Initialize the service with compiled regex patterns."""
        # Compile monetary patterns
        self._monetary_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.MONETARY_PATTERNS
        ]

        # Compile finding type patterns
        self._finding_type_patterns = {
            ft: [re.compile(p, re.IGNORECASE) for p in patterns]
            for ft, patterns in self.FINDING_TYPE_PATTERNS.items()
        }

        # Compile recommendation patterns
        self._recommendation_patterns = [
            re.compile(p, re.IGNORECASE | re.DOTALL)
            for p in self.RECOMMENDATION_PATTERNS
        ]

        # Compile target entity patterns
        self._target_entity_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TARGET_ENTITY_PATTERNS
        ]

        # Compile section type patterns
        self._section_type_patterns = {
            st: [re.compile(p, re.IGNORECASE) for p in patterns]
            for st, patterns in self.SECTION_TYPE_PATTERNS.items()
        }

        # Compile entity patterns (P3-1: NO IGNORECASE - capitalization matters for entities)
        self._entity_patterns = {
            entity_type: [re.compile(p) for p in patterns]
            for entity_type, patterns in self.ENTITY_PATTERNS.items()
        }

        # Compile scheme rejection patterns
        self._scheme_reject_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SCHEME_REJECT_PATTERNS
        ]

        # P1-1: Report type (will be set per document)
        self._current_report_type = "general"

        # P1-2: Initialize enhanced semantic pattern matcher
        self._semantic_matcher = semantic_patterns.SemanticPatternMatcher()

        # P1-3: Initialize evidence linker
        self._evidence_linker = evidence_linker.EvidenceLinker()

        # P3-3: Initialize temporal extractor
        self._temporal_extractor = TemporalExtractor()

        # P3-5: Initialize annexure linker
        self._annexure_linker = AnnexureLinker()

        # P3-6: Initialize cross-reference resolver
        self._xref_resolver = CrossReferenceResolver()

        print("SemanticEnrichmentService initialized with enhanced pattern matching, evidence linking, temporal extraction, annexure linking, and cross-reference resolution.")

    # ==================== P1-1: REPORT TYPE HELPERS ====================

    def _get_report_type_patterns(self) -> List[re.Pattern]:
        """
        Get compiled patterns for the current report type.

        Returns:
            List of compiled regex patterns specific to the report type
        """
        profile = report_type_profiles.get_profile(self._current_report_type)
        patterns = profile.get("finding_patterns", [])
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def _has_report_type_indicator(self, text: str) -> bool:
        """
        Check if text matches report-type specific finding patterns.

        Args:
            text: Text to check

        Returns:
            True if text matches report-type specific patterns
        """
        patterns = self._get_report_type_patterns()
        for pattern in patterns:
            if pattern.search(text):
                return True
        return False

    # ==================== MAIN ENTRY POINT ====================

    def enrich_document(
        self,
        report_id: str,
        report_metadata: Dict,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        task: Optional[DocumentTask] = None,
    ) -> SemanticEnrichment:
        """
        Run all enrichment extractions on a document.

        Args:
            report_id: Unique report identifier
            report_metadata: Report metadata dict
            parent_chunks: List of parent chunk dicts
            child_chunks: List of child chunk dicts
            task: Optional DocumentTask for report type detection (P1-1)

        Returns:
            SemanticEnrichment object with all extracted data
        """
        print(f"Enriching document: {report_id}")

        # P1-1: Detect report type for type-aware extraction
        if task:
            self._current_report_type = report_type_profiles.detect_report_type(task)
        else:
            # Fallback: try to detect from metadata
            self._current_report_type = report_type_profiles.normalize_report_type(
                report_metadata.get("report_type", "general")
            )
        print(f"  Detected report type: {self._current_report_type}")

        # 1. Classify sections
        section_classifications = self._classify_sections(parent_chunks)
        print(f"  Classified {len(section_classifications)} sections")

        # 2. Extract findings (now report-type aware and tier-specific severity)
        government_body_type = report_metadata.get("government_body_type", "union")
        findings = self._extract_findings(report_id, child_chunks, government_body_type)
        print(f"  Extracted {len(findings)} findings")

        # 3. P4-3: Extract recommendations with multi-strategy extractor
        from src.parsing_pipeline.modules.enrichment.recommendation_extractor import RecommendationExtractor
        rec_extractor = RecommendationExtractor()
        raw_recs = rec_extractor.extract_all(
            report_id, parent_chunks, child_chunks,
            [s.model_dump() for s in section_classifications]
        )

        # Convert to Recommendation data contracts
        recommendations = []
        for i, raw in enumerate(raw_recs):
            recommendations.append(Recommendation(
                recommendation_id=f"{report_id}_rec_{i+1:03d}",
                report_id=report_id,
                text=raw.text,
                summary=raw.text[:200],
                target_entity=raw.target_entity,
                action_required=raw.action_required,
                chapter=raw.chapter,
                section=raw.section,
                page=raw.page,
                source_chunk_id=raw.source_chunk_id,
                status="pending",
                extraction_strategy=raw.extraction_strategy,  # P4-3
                rec_number=raw.rec_number,  # P4-3
                paragraph_citations=raw.paragraph_citations,  # P4-3
            ))

        # Print extraction strategy breakdown
        structural_count = sum(1 for r in raw_recs if r.extraction_strategy == "structural")
        numbered_count = sum(1 for r in raw_recs if r.extraction_strategy == "numbered")
        verb_count = sum(1 for r in raw_recs if r.extraction_strategy == "verb")
        print(
            f"  P4-3: Extracted {len(recommendations)} recommendations "
            f"(structural={structural_count}, numbered={numbered_count}, verb={verb_count})"
        )

        # 4. Link findings to recommendations
        self._link_findings_to_recommendations(findings, recommendations)

        # 5. P1-3: Create evidence links for findings
        evidence_links_map = self._link_evidence_to_findings(findings, child_chunks)
        print(f"  Created evidence links for {len(evidence_links_map)} findings")

        # 5b. P3-5: Link findings to annexures
        annexure_links = self._annexure_linker.link_annexures(
            child_chunks, parent_chunks,
            [f.model_dump() for f in findings]
        )
        resolved = sum(1 for l in annexure_links if l["resolved"])
        print(f"  Annexure links: {len(annexure_links)} references, {resolved} resolved")

        # 6. Extract entities
        entities = self._extract_entities(child_chunks)
        print(
            f"  Extracted entities: {', '.join(f'{k}={len(v)}' for k, v in entities.items())}"
        )

        # 6b. P4-2: Detect box elements
        box_elements = self._detect_box_elements(child_chunks)
        if box_elements:
            print(f"  P4-2: Detected {len(box_elements)} box elements")

        # 6c. P4-4: Parse executive summary
        from src.parsing_pipeline.modules.enrichment.executive_summary_parser import ExecutiveSummaryParser
        exec_parser = ExecutiveSummaryParser()
        exec_summary_index = exec_parser.parse_executive_summary(
            parent_chunks, child_chunks,
            [s.model_dump() for s in section_classifications]
        )
        if exec_summary_index:
            print(
                f"  P4-4: Exec summary: {exec_summary_index['total_items']} items, "
                f"{exec_summary_index['resolution_rate']*100:.0f}% citations resolved"
            )

        # 7. P3-3: Extract temporal metadata
        temporal_coverage = self._temporal_extractor.extract_temporal_metadata(
            child_chunks, [s.model_dump() for s in section_classifications]
        )
        print(
            f"  Temporal: audit_period={temporal_coverage.get('audit_period')}, "
            f"ref_years={len(temporal_coverage.get('reference_years', []))}"
        )

        # Annotate findings with temporal context
        for finding in findings:
            finding.reference_years = self._temporal_extractor.extract_reference_years(finding.text)
            if temporal_coverage.get("audit_period"):
                finding.audit_period = temporal_coverage["audit_period"]

        # 8. P3-6: Resolve cross-chunk references
        cross_references = self._xref_resolver.resolve_references(child_chunks, parent_chunks)
        resolved_xrefs = sum(1 for x in cross_references if x["resolved"])
        print(f"  Cross-references: {len(cross_references)} found, {resolved_xrefs} resolved")

        # 9. Calculate statistics (includes report type)
        statistics = self._calculate_statistics(
            report_metadata, findings, recommendations, section_classifications
        )

        return SemanticEnrichment(
            report_id=report_id,
            findings=[f.model_dump() for f in findings],
            recommendations=[r.model_dump() for r in recommendations],
            section_classifications=[s.model_dump() for s in section_classifications],
            statistics=statistics,
            entities=entities,
            annexure_links=annexure_links,
            cross_references=cross_references,
            temporal_coverage=temporal_coverage,
            box_elements=box_elements,  # P4-2
            executive_summary_index=exec_summary_index,  # P4-4
        )

    # ==================== MONETARY EXTRACTION ====================

    def _extract_monetary_values(self, text: str) -> List[MonetaryValue]:
        """Extract all monetary values from text."""
        monetary_values = []
        seen = set()  # Avoid duplicates

        for pattern in self._monetary_patterns:
            for match in pattern.finditer(text):
                raw_text = match.group(0).strip()

                # Skip if we've seen this exact text
                if raw_text in seen:
                    continue
                seen.add(raw_text)

                try:
                    # Extract amount and unit
                    groups = match.groups()
                    amount_str = groups[0].replace(",", "")
                    amount = float(amount_str)
                    unit = groups[1].lower() if len(groups) > 1 and groups[1] else None

                    # Normalize to paise
                    multiplier = self.UNIT_MULTIPLIERS.get(unit, 100)
                    normalized_inr = int(amount * multiplier)

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

    # ==================== FINDING EXTRACTION ====================

    def _extract_findings(
        self,
        report_id: str,
        child_chunks: List[Dict],
        government_body_type: str = "union",
    ) -> List[Finding]:
        """
        Extract audit findings from child chunks.

        Args:
            report_id: Unique report identifier
            child_chunks: List of child chunk dicts
            government_body_type: "union", "state", or "local_body" (default: "union")

        Returns:
            List of Finding objects
        """
        findings = []
        finding_counter = 0

        for chunk in child_chunks:
            # Only process paragraphs and lists
            if chunk.get("content_type") not in ("paragraph", "list"):
                continue

            content = chunk.get("content", "")

            # Skip very short content
            if len(content) < 50:
                continue

            # P1-2: Use enhanced semantic pattern matcher
            patterns_matched = self._semantic_matcher.match_patterns(content)
            confidence_score = self._semantic_matcher.calculate_finding_confidence(
                content, patterns_matched, self._current_report_type
            )

            # Check if this looks like a finding (using enhanced logic)
            finding_type = self._detect_finding_type(content)
            monetary_values = self._extract_monetary_values(content)

            # Decision logic: Use confidence score from semantic matcher
            # Threshold: 0.4 for findings (can be adjusted)
            is_finding_by_confidence = confidence_score >= 0.4

            # Legacy indicators (for backward compatibility)
            has_monetary = len(monetary_values) > 0
            has_finding_type = finding_type != FindingType.OTHER

            finding_indicators = [
                r"audit\s+observed",
                r"audit\s+noticed",
                r"audit\s+found",
                r"it\s+was\s+observed",
                r"it\s+was\s+noticed",
                r"scrutiny\s+revealed",
                r"examination\s+revealed",
                r"review\s+revealed",
                r"test\s+check\s+revealed",
            ]
            has_indicator = any(
                re.search(p, content, re.IGNORECASE) for p in finding_indicators
            )

            # Decide if this is a finding (P1-2 enhanced logic)
            is_finding = (
                is_finding_by_confidence  # Primary: Use semantic matcher confidence
                or (has_monetary and (has_finding_type or has_indicator))  # Legacy: monetary + type/indicator
                or (has_finding_type and has_indicator)  # Legacy: type + indicator
            )

            if not is_finding:
                continue

            finding_counter += 1

            # Calculate total monetary value
            total_amount = sum(mv.normalized_inr for mv in monetary_values)

            # Determine severity based on amount (tier-specific thresholds)
            severity = self._calculate_severity(total_amount, finding_type, government_body_type)

            # Extract hierarchy info
            hierarchy = chunk.get("metadata", {}).get("hierarchy", {})
            chapter = hierarchy.get("level_1") or hierarchy.get("level_2")
            section = hierarchy.get("level_3") or hierarchy.get("level_4")

            # Generate summary (first sentence or first 200 chars)
            summary = self._generate_summary(content)

            # Extract entities mentioned
            entities = self._extract_entities_from_text(content)

            # P1-2: Extract pattern types from matches
            pattern_types = [match.pattern_type for match in patterns_matched]

            finding = Finding(
                finding_id=f"{report_id}_finding_{finding_counter:03d}",
                report_id=report_id,
                text=content,
                summary=summary,
                finding_type=finding_type.value,
                severity=severity.value,
                monetary_values=[mv.to_dict() for mv in monetary_values],
                total_amount_inr=total_amount,
                confidence=confidence_score,  # P1-2: Add confidence score
                pattern_types=pattern_types,  # P1-2: Add matched pattern types
                chapter=chapter,
                section=section,
                page=chunk.get("metadata", {})
                .get("location", {})
                .get("page_physical", 0),
                source_chunk_id=chunk.get("chunk_id", ""),
                entities_mentioned=entities,
            )

            findings.append(finding)

        return findings

    def _detect_finding_type(self, text: str) -> FindingType:
        """Detect the type of finding based on text patterns."""
        text_lower = text.lower()

        # Check each finding type
        for finding_type, patterns in self._finding_type_patterns.items():
            for pattern in patterns:
                if pattern.search(text_lower):
                    return finding_type

        return FindingType.OTHER

    def _calculate_severity(
        self,
        total_amount_inr: int,
        finding_type: FindingType,
        government_body_type: str = "union",
    ) -> Severity:
        """
        Calculate severity based on amount and finding type using tier-specific thresholds.

        Args:
            total_amount_inr: Total monetary amount in paise
            finding_type: Type of finding
            government_body_type: "union", "state", or "local_body" (default: "union")

        Returns:
            Severity level
        """
        # Convert paise to crore for comparison
        amount_crore = total_amount_inr / 10_000_000_00

        # Get tier-specific thresholds (default to union for backward compatibility)
        thresholds = self.SEVERITY_THRESHOLDS.get(government_body_type, self.SEVERITY_THRESHOLDS["union"])

        # Amount-based severity using tier-specific thresholds
        if amount_crore >= thresholds["critical"]:
            return Severity.CRITICAL
        elif amount_crore >= thresholds["high"]:
            return Severity.HIGH
        elif amount_crore >= thresholds["medium"]:
            return Severity.MEDIUM

        # Type-based severity for low-amount findings
        if finding_type == FindingType.FRAUD_MISAPPROPRIATION:
            return Severity.HIGH
        elif finding_type in (
            FindingType.SYSTEM_DEFICIENCY,
            FindingType.NON_COMPLIANCE,
        ):
            return Severity.MEDIUM

        return Severity.LOW

    # ==================== RECOMMENDATION EXTRACTION ====================

    def _extract_recommendations(
        self,
        report_id: str,
        child_chunks: List[Dict],
    ) -> List[Recommendation]:
        """Extract recommendations from child chunks."""
        recommendations = []
        rec_counter = 0
        seen_texts = set()  # Avoid duplicates

        for chunk in child_chunks:
            if chunk.get("content_type") not in ("paragraph", "list"):
                continue

            content = chunk.get("content", "")

            # Check each recommendation pattern
            for pattern in self._recommendation_patterns:
                matches = pattern.finditer(content)

                for match in matches:
                    # Get the matched recommendation text
                    if match.groups():
                        rec_text = match.group(1).strip()
                    else:
                        rec_text = match.group(0).strip()

                    # Skip if too short or duplicate
                    if len(rec_text) < 20:
                        continue

                    # Normalize for deduplication
                    normalized = " ".join(rec_text.lower().split())[:100]
                    if normalized in seen_texts:
                        continue
                    seen_texts.add(normalized)

                    rec_counter += 1

                    # Extract target entity
                    target_entity = self._extract_target_entity(content)

                    # Extract hierarchy info
                    hierarchy = chunk.get("metadata", {}).get("hierarchy", {})
                    chapter = hierarchy.get("level_1") or hierarchy.get("level_2")
                    section = hierarchy.get("level_3") or hierarchy.get("level_4")

                    # Generate summary
                    summary = rec_text[:200] + ("..." if len(rec_text) > 200 else "")

                    recommendation = Recommendation(
                        recommendation_id=f"{report_id}_rec_{rec_counter:03d}",
                        report_id=report_id,
                        text=rec_text,
                        summary=summary,
                        target_entity=target_entity,
                        action_required=self._extract_action_verb(rec_text),
                        chapter=chapter,
                        section=section,
                        page=chunk.get("metadata", {})
                        .get("location", {})
                        .get("page_physical", 0),
                        source_chunk_id=chunk.get("chunk_id", ""),
                    )

                    recommendations.append(recommendation)

        return recommendations

    def _extract_target_entity(self, text: str) -> Optional[str]:
        """Extract the target entity (ministry/department) from recommendation."""
        for pattern in self._target_entity_patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return None

    def _extract_action_verb(self, text: str) -> Optional[str]:
        """Extract the action verb phrase from recommendation."""
        action_patterns = [
            r"should\s+(\w+(?:\s+\w+){0,3})",
            r"needs?\s+to\s+(\w+(?:\s+\w+){0,3})",
            r"must\s+(\w+(?:\s+\w+){0,3})",
            r"may\s+consider\s+(\w+(?:\s+\w+){0,3})",
        ]

        for pattern in action_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _link_findings_to_recommendations(
        self,
        findings: List[Finding],
        recommendations: List[Recommendation],
    ) -> None:
        """Link related findings and recommendations based on proximity and content."""
        # Simple heuristic: link by page proximity and chapter
        for rec in recommendations:
            related = []
            for finding in findings:
                # Same chapter
                if rec.chapter and finding.chapter and rec.chapter == finding.chapter:
                    # Within 5 pages
                    if abs(rec.page - finding.page) <= 5:
                        related.append(finding.finding_id)

            rec.related_finding_ids = related[:5]  # Max 5 related findings

    def _link_evidence_to_findings(
        self,
        findings: List[Finding],
        child_chunks: List[Dict],
    ) -> Dict[str, List]:
        """
        P1-3: Link findings to their supporting evidence.

        Args:
            findings: List of Finding objects
            child_chunks: List of child chunk dicts

        Returns:
            Dict mapping finding_id to list of evidence links
        """
        # Convert findings to dicts for evidence linker
        finding_dicts = [f.model_dump() for f in findings]

        # Extract tables from child_chunks (tables have content_type="table")
        tables = [chunk for chunk in child_chunks if chunk.get("content_type") == "table"]

        # Create evidence links
        evidence_links_map = self._evidence_linker.link_all_findings(
            finding_dicts, tables, child_chunks
        )

        # Update findings with their evidence links
        for finding in findings:
            if finding.finding_id in evidence_links_map:
                links = evidence_links_map[finding.finding_id]
                finding.evidence_links = [link.to_dict() for link in links]

        return evidence_links_map

    # ==================== SECTION CLASSIFICATION ====================

    def _classify_sections(
        self,
        parent_chunks: List[Dict],
    ) -> List[SectionClassification]:
        """Classify parent chunks by section type."""
        classifications = []

        for chunk in parent_chunks:
            section_title = chunk.get("toc_entry", "")
            hierarchy = chunk.get("hierarchy", {})

            # Combine hierarchy for better matching
            full_context = " ".join(
                [str(v) for v in hierarchy.values()] + [section_title]
            )

            # Find best matching section type
            best_type = SectionType.OTHER
            best_confidence = 0.0

            for section_type, patterns in self._section_type_patterns.items():
                for pattern in patterns:
                    if pattern.search(full_context):
                        # Higher confidence for exact title match
                        confidence = 0.9 if pattern.search(section_title) else 0.7
                        if confidence > best_confidence:
                            best_type = section_type
                            best_confidence = confidence

            classifications.append(
                SectionClassification(
                    chunk_id=chunk.get("chunk_id", ""),
                    section_title=section_title,
                    section_type=best_type.value,
                    confidence=best_confidence,
                )
            )

        return classifications

    # ==================== ENTITY EXTRACTION ====================

    def _clean_entity(self, raw: str) -> Optional[str]:
        """
        P3-1: Post-process a raw entity match. Returns None if garbage.

        Filters out:
        - Sentence fragments (starts with verbs/articles/prepositions)
        - Too short (<4 chars) or too long (>60 chars)
        - Lowercase starts
        - Too many words (>8 = likely sentence fragment, accounting for special chars)
        - Contains sentence-ending punctuation mid-string

        Args:
            raw: Raw entity string extracted by regex

        Returns:
            Cleaned entity string or None if it should be rejected
        """
        cleaned = " ".join(raw.split()).strip()

        # Length bounds
        if len(cleaned) < 4 or len(cleaned) > 60:
            return None

        # Must start with uppercase
        if not cleaned[0].isupper():
            return None

        # Reject if first word is a common verb/article/preposition (sentence fragment)
        first_word = cleaned.split()[0].lower()
        if first_word in self.ENTITY_REJECT_VERBS:
            return None

        # Reject if >8 words (likely a sentence fragment, not a proper name)
        # Allow up to 8 to accommodate names like "Ministry of Micro, Small & Medium Enterprises"
        if len(cleaned.split()) > 8:
            return None

        # Reject if contains sentence-ending punctuation mid-string
        if re.search(r'[.!?]\s+[A-Z]', cleaned):
            return None

        return cleaned

    def _extract_entities(
        self,
        child_chunks: List[Dict],
    ) -> Dict[str, List[str]]:
        """Extract named entities from all child chunks."""
        entities: Dict[str, set] = {
            entity_type: set() for entity_type in self.ENTITY_PATTERNS.keys()
        }

        for chunk in child_chunks:
            content = chunk.get("content", "")

            for entity_type, patterns in self._entity_patterns.items():
                for pattern in patterns:
                    matches = pattern.findall(content)
                    # P3-1: Use _clean_entity filter
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]

                        # Apply scheme rejection filter
                        if entity_type == "schemes":
                            if any(rej.search(match) for rej in self._scheme_reject_patterns):
                                continue

                        cleaned = self._clean_entity(match)
                        if cleaned:
                            entities[entity_type].add(cleaned)

        # P3-1: Deduplicate by substring
        # If "National Highways Authority" and "National Highways Authority of India"
        # both exist, keep the longer one
        for entity_type in entities:
            deduped = set()
            sorted_ents = sorted(entities[entity_type], key=len, reverse=True)
            for ent in sorted_ents:
                ent_lower = ent.lower()
                if not any(ent_lower in existing.lower() for existing in deduped):
                    deduped.add(ent)
            entities[entity_type] = deduped

        # Convert sets to sorted lists
        return {k: sorted(list(v)) for k, v in entities.items()}

    def _extract_entities_from_text(self, text: str) -> List[str]:
        """Extract entities from a single text block."""
        entities = []

        for entity_type, patterns in self._entity_patterns.items():
            for pattern in patterns:
                matches = pattern.findall(text)
                # P3-1: Use _clean_entity filter
                for match in matches:
                    if isinstance(match, tuple):
                        match = match[0]

                    # Apply scheme rejection filter
                    if entity_type == "schemes":
                        if any(rej.search(match) for rej in self._scheme_reject_patterns):
                            continue

                    cleaned = self._clean_entity(match)
                    if cleaned:
                        entities.append(cleaned)

        return list(set(entities))[:10]  # Max 10 entities per finding

    # ==================== P4-2: BOX ELEMENT DETECTION ====================

    def _detect_box_elements(
        self, child_chunks: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        P4-2: Detect "Box X.X" illustrative elements across child chunks.

        Strategy:
        1. Scan for "Box X.X: Title" pattern in chunk content
        2. The chunk containing the caption represents the box
        3. Do NOT tag chunks just because they're on a colored background

        Only boxes with explicit "Box X.X" captions are detected.

        Args:
            child_chunks: List of child chunk dictionaries

        Returns:
            List of box descriptors with metadata
        """
        boxes = []
        compiled = [re.compile(p, re.IGNORECASE) for p in self.BOX_CAPTION_PATTERNS]

        for i, chunk in enumerate(child_chunks):
            content = chunk.get("content", "")

            for pattern in compiled:
                match = pattern.search(content[:200])  # Only check start of chunk
                if match:
                    box_id = match.group(1).strip()
                    box_title = match.group(2).strip() if match.lastindex >= 2 else ""

                    # Classify box subtype
                    box_subtype = "general"
                    content_lower = (box_title + " " + content).lower()
                    for subtype, keywords in self.BOX_SUBTYPE_KEYWORDS.items():
                        if any(kw in content_lower for kw in keywords):
                            box_subtype = subtype
                            break

                    boxes.append({
                        "box_id": re.sub(r'\s+', '_', box_id.lower()),
                        "box_number": box_id,
                        "box_title": box_title,
                        "box_subtype": box_subtype,
                        "caption_chunk_id": chunk.get("chunk_id"),
                        "page_physical": chunk.get("source_page_physical"),
                        "parent_section": chunk.get("hierarchy", {}),
                    })
                    break  # One box per chunk

        return boxes

    # ==================== STATISTICS ====================

    def _calculate_statistics(
        self,
        report_metadata: Dict,
        findings: List[Finding],
        recommendations: List[Recommendation],
        sections: List[SectionClassification],
    ) -> Dict[str, Any]:
        """Calculate aggregate statistics for the report."""

        # Monetary statistics
        total_monetary = sum(f.total_amount_inr for f in findings)
        total_monetary_crore = total_monetary / 10_000_000_00

        # Finding statistics by type
        findings_by_type = {}
        for f in findings:
            ft = f.finding_type
            if ft not in findings_by_type:
                findings_by_type[ft] = {"count": 0, "total_inr": 0}
            findings_by_type[ft]["count"] += 1
            findings_by_type[ft]["total_inr"] += f.total_amount_inr

        # Convert to crore for readability
        for ft in findings_by_type:
            findings_by_type[ft]["total_crore"] = (
                findings_by_type[ft]["total_inr"] / 10_000_000_00
            )

        # Severity distribution
        severity_counts = {}
        for f in findings:
            sev = f.severity
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Section type distribution
        section_type_counts = {}
        for s in sections:
            st = s.section_type
            section_type_counts[st] = section_type_counts.get(st, 0) + 1

        # Recommendation statistics
        target_entity_counts = {}
        for r in recommendations:
            if r.target_entity:
                target_entity_counts[r.target_entity] = (
                    target_entity_counts.get(r.target_entity, 0) + 1
                )

        return {
            "report_info": {
                "ministry": report_metadata.get("ministry", "Unknown"),
                "sector": report_metadata.get("sector", "Unknown"),
                "report_type": report_metadata.get("report_type", "Unknown"),
                "detected_report_type": self._current_report_type,  # P1-1: Add detected type
                "publication_date": report_metadata.get("publication_date", "Unknown"),
            },
            "findings": {
                "total_count": len(findings),
                "total_monetary_inr": total_monetary,
                "total_monetary_crore": round(total_monetary_crore, 2),
                "by_type": findings_by_type,
                "by_severity": severity_counts,
            },
            "recommendations": {
                "total_count": len(recommendations),
                "by_target_entity": target_entity_counts,
            },
            "sections": {
                "total_count": len(sections),
                "by_type": section_type_counts,
            },
        }

    # ==================== UTILITIES ====================

    def _generate_summary(self, text: str, max_length: int = 200) -> str:
        """Generate a summary from text (first sentence or truncated)."""
        # Try to get first sentence
        sentence_end = re.search(r"[.!?]\s", text)
        if sentence_end and sentence_end.start() < max_length:
            return text[: sentence_end.start() + 1]

        # Otherwise truncate
        if len(text) <= max_length:
            return text

        # Find a good break point
        truncated = text[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:
            return truncated[:last_space] + "..."

        return truncated + "..."


# ==================== STANDALONE FUNCTIONS ====================


def enrich_report_file(
    input_path: str,
    output_path: Optional[str] = None,
) -> Dict:
    """
    Enrich a single report JSON file.

    Args:
        input_path: Path to *_chunks.json file
        output_path: Optional output path (defaults to *_enriched.json)

    Returns:
        Enrichment results dict
    """
    import json
    from pathlib import Path

    # Load input
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Initialize service
    service = SemanticEnrichmentService()

    # Run enrichment
    enrichment = service.enrich_document(
        report_id=data["report_metadata"]["report_id"],
        report_metadata=data["report_metadata"],
        parent_chunks=data["parent_chunks"],
        child_chunks=data["child_chunks"],
    )

    # Add to data
    data["semantic_enrichment"] = enrichment.model_dump()

    # Determine output path
    if output_path is None:
        input_file = Path(input_path)
        output_path = str(input_file.parent / f"{input_file.stem}_enriched.json")

    # Save output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Enriched output saved to: {output_path}")

    return enrichment.model_dump()


def enrich_all_reports(
    input_dir: str = "data/processed",
    output_dir: Optional[str] = None,
) -> List[Dict]:
    """
    Enrich all report files in a directory.

    Args:
        input_dir: Directory containing *_chunks.json files
        output_dir: Optional output directory (defaults to input_dir)

    Returns:
        List of enrichment results
    """
    from pathlib import Path

    input_path = Path(input_dir)
    output_path = Path(output_dir) if output_dir else input_path
    output_path.mkdir(parents=True, exist_ok=True)

    results = []
    chunk_files = list(input_path.glob("*_chunks.json"))

    print(f"Found {len(chunk_files)} report files to enrich")

    for i, chunk_file in enumerate(sorted(chunk_files), 1):
        print(f"\n[{i}/{len(chunk_files)}] Processing: {chunk_file.name}")

        output_file = output_path / f"{chunk_file.stem}_enriched.json"

        try:
            result = enrich_report_file(str(chunk_file), str(output_file))
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    # Print summary
    print("\n" + "=" * 60)
    print("ENRICHMENT SUMMARY")
    print("=" * 60)

    total_findings = sum(len(r.get("findings", [])) for r in results)
    total_recommendations = sum(len(r.get("recommendations", [])) for r in results)
    total_monetary = sum(
        r.get("statistics", {}).get("findings", {}).get("total_monetary_crore", 0)
        for r in results
    )

    print(f"Reports processed: {len(results)}")
    print(f"Total findings extracted: {total_findings}")
    print(f"Total recommendations extracted: {total_recommendations}")
    print(f"Total monetary value: ₹{total_monetary:,.2f} crore")

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python semantic_enrichment_service.py <chunks.json>")
        print("  python semantic_enrichment_service.py --all <input_dir>")
        sys.exit(1)

    if sys.argv[1] == "--all":
        input_dir = sys.argv[2] if len(sys.argv) > 2 else "data/processed"
        enrich_all_reports(input_dir)
    else:
        enrich_report_file(sys.argv[1])
