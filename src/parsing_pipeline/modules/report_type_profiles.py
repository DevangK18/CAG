"""
Report Type Profiles - Type-specific extraction configurations for CAG audit reports.

This module defines extraction patterns and configurations tailored to different
audit report types (Compliance, Performance, Financial). These profiles enable
report-type aware semantic enrichment without requiring LLM calls.

Part of Phase 1 Enhancement (P1-1: Report Type Adaptation)
"""

from typing import Dict, List, Optional, Any
from src.core.data_contracts import DocumentTask


# ═══════════════════════════════════════════════════════════════════════
# REPORT TYPE PROFILES
# ═══════════════════════════════════════════════════════════════════════

REPORT_PROFILES: Dict[str, Dict[str, Any]] = {
    "compliance": {
        "finding_patterns": [
            r"(?:audit|scrutiny)\s+(?:revealed|observed|noticed)",
            r"(?:non-?compliance|violation|deviation)",
            r"(?:contrary|violation)\s+(?:to|of)\s+(?:rules?|provisions?)",
            r"(?:irregular|improper|unauthorized)\s+(?:expenditure|payment)",
            r"(?:in\s+)?contravention\s+(?:of|to)",
            r"(?:without|in\s+absence\s+of)\s+(?:approval|sanction|authorization)",
        ],
        "section_markers": {
            "findings": ["audit findings", "observations", "results of audit", "irregularities"],
            "recommendations": ["recommendations", "suggested actions", "way forward"],
            "response": ["ministry's response", "reply", "comments"],
        },
        "monetary_context": "irregular_expenditure",
        "evidence_weight": "high",
        "confidence_boost": 1.2,
        "description": "Compliance audits focus on adherence to rules, regulations, and procedures",
    },

    "performance": {
        "finding_patterns": [
            r"(?:shortfall|gap|deficiency)\s+(?:in|of)",
            r"(?:targets?|objectives?)\s+(?:not|were not)\s+(?:achieved|met)",
            r"(?:performance|outcome)\s+(?:below|under)",
            r"(?:delay|delayed)\s+(?:in|by)",
            r"(?:ineffective|inefficient|sub-?optimal)",
            r"(?:utilization|achievement)\s+(?:was|were)\s+(?:only|merely)\s+\d+%?",
        ],
        "section_markers": {
            "scope": ["audit scope", "coverage", "methodology"],
            "criteria": ["audit criteria", "benchmarks", "standards"],
            "findings": ["audit findings", "observations", "performance assessment"],
            "impact": ["impact", "effect", "consequence"],
        },
        "monetary_context": "performance_shortfall",
        "evidence_weight": "medium",
        "confidence_boost": 1.0,
        "description": "Performance audits assess economy, efficiency, and effectiveness of programs",
    },

    "financial": {
        "finding_patterns": [
            r"(?:misstatement|error|discrepancy)",
            r"(?:understatement|overstatement)",
            r"(?:unreconciled|unexplained)\s+(?:differences?|balances?)",
            r"(?:incorrect|improper)\s+(?:accounting|classification)",
            r"(?:non-?disclosure|omission)",
            r"(?:financial\s+)?irregularit(?:y|ies)",
        ],
        "section_markers": {
            "opinion": ["audit opinion", "auditor's report", "qualified opinion"],
            "notes": ["notes to accounts", "significant accounting", "financial statements"],
            "observations": ["audit observations", "financial irregularities"],
        },
        "monetary_context": "financial_irregularity",
        "evidence_weight": "high",
        "confidence_boost": 1.15,
        "description": "Financial audits examine accuracy and completeness of financial statements",
    },

    "general": {
        "finding_patterns": [
            r"audit\s+(?:revealed|observed|found)",
            r"(?:issue|problem|concern)\s+(?:identified|noted)",
            r"(?:loss|damage|wastage)",
        ],
        "section_markers": {
            "findings": ["findings", "observations"],
            "recommendations": ["recommendations"],
        },
        "monetary_context": "general",
        "evidence_weight": "medium",
        "confidence_boost": 1.0,
        "description": "General audit reports without specific type classification",
    },

    "atir": {
        "finding_patterns": [
            # ATIR-specific patterns
            r"(?:not|non-)?\s*maintained\s+(?:on\s+)?PRIASoft",
            r"(?:not|non-?)\s*preparation\s+of\s+accounts?",
            r"(?:not|non-?)\s*submission\s+of\s+(?:utilisation|utilization)\s+certificates?",
            r"UCs?\s+(?:not|pending|outstanding)",
            r"accounts?\s+(?:not|were\s+not)\s+(?:maintained|prepared|finali[sz]ed)",
            r"(?:non-?)?reconciliation\s+of\s+(?:funds?|balances?|accounts?)",
            r"Finance\s+Commission\s+(?:funds?|grants?)",
            r"(?:Gram|Zilla)\s+Panchayats?",
            r"Municipal\s+(?:Corporation|Council)",
            r"(?:PRI|ULB)s?\s+(?:failed|did\s+not)",
        ],
        "section_markers": {
            "findings": ["results of audit", "chapter 2", "chapter 4", "audit findings", "observations"],
            "profile": ["profile", "chapter 1", "chapter 3", "background"],  # NOT findings sections
            "recommendations": ["recommendations", "way forward", "conclusion"],
        },
        "monetary_context": "local_body_funds",
        "evidence_weight": "medium",  # Lower than compliance - many procedural findings
        "confidence_boost": 0.9,  # Slightly lower - findings less explicit than Union compliance
        "description": "ATIR (Annual Technical Inspection Report) for Local Bodies - PRIs and ULBs",
        "expected_finding_types": [
            "accounting_irregularity",
            "fund_utilization_failure",
            "non_compliance",
            "fraud_misappropriation"
        ],
        "severity_context": "local_body",
    },

    "state_commercial": {
        "finding_patterns": [
            # State PSE patterns
            r"(?:lying|remained)\s+(?:idle|unutili[sz]ed)",
            r"(?:not|non-?)\s*reali[sz]ation\s+of\s+(?:dues|rent|revenue)",
            r"(?:not|non-?)\s*recovery\s+of\s+(?:dues|revenue)",
            r"(?:outstanding|unreali[sz]ed|unrecovered)\s+dues",
            r"arrears\s+(?:of\s+revenue|amounting)",
            r"loss\s+of\s+revenue",
            r"(?:low|poor)\s+occupancy",
            r"(?:State|State-owned)\s+(?:Corporation|Enterprise|PSE|SPSE)",
            r"(?:idle|unused)\s+(?:assets?|equipment|machinery|infrastructure)",
            r"blocking\s+of\s+funds?",
        ],
        "section_markers": {
            "findings": ["audit findings", "observations", "performance of PSE", "financial position"],
            "recommendations": ["recommendations", "suggested actions"],
            "financial": ["financial statements", "profit and loss", "balance sheet"],
        },
        "monetary_context": "state_pse_revenue",
        "evidence_weight": "high",  # Commercial audits are evidence-heavy
        "confidence_boost": 1.1,
        "description": "State Commercial Audit Reports - State Public Sector Enterprises",
        "expected_finding_types": [
            "idle_assets",
            "non_realization_of_dues",
            "loss_of_revenue",
            "wasteful_expenditure",
            "irregular_expenditure"
        ],
        "severity_context": "state",
    },

    "state_performance": {
        "finding_patterns": [
            # State scheme implementation patterns
            r"work\s+(?:was|were)\s+(?:stopped|stalled|abandoned|incomplete)",
            r"(?:not|could\s+not\s+be)\s+completed",
            r"only\s+\d+%?\s+(?:of\s+work|works?)\s+(?:executed|completed)",
            r"balance\s+works?\s+not\s+(?:taken\s+up|completed)",
            r"(?:inordinate|undue)\s+delay\s+(?:in\s+completion)?",
            r"(?:time|cost)\s+overrun",
            r"funds?\s+remained\s+(?:unspent|unutili[sz]ed)",
            r"(?:targets?|objectives?)\s+(?:not|were\s+not)\s+(?:achieved|met)",
            r"(?:shortfall|gap)\s+in\s+(?:implementation|achievement)",
            r"scheme\s+(?:implementation|performance)",
        ],
        "section_markers": {
            "scope": ["audit scope", "coverage", "audit universe"],
            "criteria": ["audit criteria", "benchmarks", "norms"],
            "findings": ["audit findings", "observations", "performance assessment", "implementation status"],
            "impact": ["impact", "outcome", "achievement", "utilization"],
            "recommendations": ["recommendations", "way forward", "conclusion"],
        },
        "monetary_context": "state_scheme_utilization",
        "evidence_weight": "medium",
        "confidence_boost": 1.0,
        "description": "State Performance Audit Reports - State scheme implementation and effectiveness",
        "expected_finding_types": [
            "incomplete_infrastructure",
            "fund_utilization_failure",
            "performance_shortfall",
            "non_compliance",
            "idle_assets"
        ],
        "severity_context": "state",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# REPORT TYPE DETECTION
# ═══════════════════════════════════════════════════════════════════════

def detect_report_type(task: DocumentTask) -> str:
    """
    Detect report type from metadata and content signals.

    Priority order:
    1. ATIR (most specific - local_body + atir category)
    2. STATE_COMMERCIAL (state + commercial)
    3. STATE_PERFORMANCE (state + performance)
    4. Explicit metadata report_type field
    5. Title-based detection (Union reports, or State reports matching by title)
    6. ToC-based detection
    7. Default to "general"

    Args:
        task: DocumentTask with metadata and scaffold

    Returns:
        Report type: "atir", "state_commercial", "state_performance",
                     "compliance", "performance", "financial", or "general"
    """
    metadata = task.initial_metadata or {}

    # Get tier-specific fields
    government_body_type = metadata.get("government_body_type", "union")
    audit_category = metadata.get("audit_category", "compliance")
    title = metadata.get("report_title", "").lower()

    # Priority 1: ATIR (most specific)
    if (
        "atir" in title
        or "annual technical inspection" in title
        or (government_body_type == "local_body" and audit_category == "atir")
    ):
        return "atir"

    # Priority 2: STATE_COMMERCIAL
    if (
        (government_body_type == "state" and audit_category == "commercial")
        or (government_body_type == "state" and "commercial" in title)
    ):
        return "state_commercial"

    # Priority 3: STATE_PERFORMANCE
    if government_body_type == "state" and audit_category == "performance":
        return "state_performance"

    # Priority 4: Check explicit metadata report_type field
    if "report_type" in metadata and metadata["report_type"]:
        detected = normalize_report_type(metadata["report_type"])
        if detected in REPORT_PROFILES:
            return detected

    # Priority 5: Analyze title (works for Union + some State reports)
    title_type = _detect_from_title(title)
    if title_type != "general":
        return title_type

    # Priority 6: Analyze ToC structure
    if task.scaffold and "toc" in task.scaffold:
        toc_type = _detect_from_toc(task.scaffold["toc"])
        if toc_type != "general":
            return toc_type

    # Default to general
    return "general"


def normalize_report_type(raw_type: str) -> str:
    """
    Normalize various report type strings to standard types.

    Args:
        raw_type: Raw report type string from metadata

    Returns:
        Normalized type: "atir", "state_commercial", "state_performance",
                        "compliance", "performance", "financial", or "general"
    """
    raw_lower = raw_type.lower().strip()

    # Direct matches
    if raw_lower in ["atir", "state_commercial", "state_performance",
                     "compliance", "performance", "financial", "general"]:
        return raw_lower

    # ATIR variations
    if "atir" in raw_lower or "annual technical inspection" in raw_lower:
        return "atir"

    # State Commercial variations
    if "state" in raw_lower and "commercial" in raw_lower:
        return "state_commercial"

    # State Performance variations
    if "state" in raw_lower and "performance" in raw_lower:
        return "state_performance"

    # Compliance variations
    if any(keyword in raw_lower for keyword in ["compliance", "regularity", "propriety"]):
        return "compliance"

    # Performance variations
    if any(keyword in raw_lower for keyword in ["performance", "economy", "efficiency", "effectiveness"]):
        return "performance"

    # Financial variations
    if any(keyword in raw_lower for keyword in ["financial", "accounts", "appropriation"]):
        return "financial"

    return "general"


def _detect_from_title(title: str) -> str:
    """Detect report type from title."""
    title_lower = title.lower()

    # Check for explicit type mentions
    if "compliance" in title_lower or "regularity" in title_lower:
        return "compliance"
    if "performance" in title_lower:
        return "performance"
    if "financial" in title_lower or "accounts" in title_lower or "appropriation" in title_lower:
        return "financial"

    return "general"


def _detect_from_toc(toc_entries: List[Dict[str, Any]]) -> str:
    """
    Detect report type from Table of Contents structure.

    Analyzes ToC entries for keywords specific to each report type.
    """
    toc_text = " ".join([
        entry.get("title", "").lower()
        for entry in toc_entries
        if isinstance(entry, dict)
    ])

    # Count signals for each type
    compliance_signals = _count_compliance_signals(toc_text)
    performance_signals = _count_performance_signals(toc_text)
    financial_signals = _count_financial_signals(toc_text)

    # Determine dominant type
    max_signals = max(compliance_signals, performance_signals, financial_signals)

    if max_signals == 0:
        return "general"

    if compliance_signals == max_signals and compliance_signals > 2:
        return "compliance"
    elif performance_signals == max_signals and performance_signals > 2:
        return "performance"
    elif financial_signals == max_signals and financial_signals > 2:
        return "financial"

    return "general"


def _count_compliance_signals(text: str) -> int:
    """Count compliance-specific keywords in text."""
    keywords = [
        "compliance", "irregularit", "audit observation", "non-compliance",
        "violation", "deviation", "propriety", "rule", "regulation",
        "unauthorized", "unapproved"
    ]
    return sum(1 for keyword in keywords if keyword in text)


def _count_performance_signals(text: str) -> int:
    """Count performance-specific keywords in text."""
    keywords = [
        "performance", "outcome", "achievement", "target", "objective",
        "efficiency", "effectiveness", "economy", "implementation",
        "utilization", "progress", "scheme", "program"
    ]
    return sum(1 for keyword in keywords if keyword in text)


def _count_financial_signals(text: str) -> int:
    """Count financial-specific keywords in text."""
    keywords = [
        "financial statement", "accounts", "appropriation", "budget",
        "receipt", "expenditure", "balance sheet", "income statement",
        "audit opinion", "qualified opinion", "accounting", "ledger"
    ]
    return sum(1 for keyword in keywords if keyword in text)


# ═══════════════════════════════════════════════════════════════════════
# PROFILE ACCESSORS
# ═══════════════════════════════════════════════════════════════════════

def get_profile(report_type: str) -> Dict[str, Any]:
    """
    Get the profile configuration for a report type.

    Args:
        report_type: Report type string

    Returns:
        Profile dictionary with finding patterns and configuration
    """
    return REPORT_PROFILES.get(report_type, REPORT_PROFILES["general"])


def get_finding_patterns(report_type: str) -> List[str]:
    """Get finding patterns for a report type."""
    profile = get_profile(report_type)
    return profile.get("finding_patterns", [])


def get_section_markers(report_type: str) -> Dict[str, List[str]]:
    """Get section markers for a report type."""
    profile = get_profile(report_type)
    return profile.get("section_markers", {})


def get_confidence_boost(report_type: str) -> float:
    """Get confidence score multiplier for a report type."""
    profile = get_profile(report_type)
    return profile.get("confidence_boost", 1.0)


def get_evidence_weight(report_type: str) -> str:
    """Get evidence weight for a report type."""
    profile = get_profile(report_type)
    return profile.get("evidence_weight", "medium")
