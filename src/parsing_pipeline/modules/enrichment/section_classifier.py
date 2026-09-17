"""
SectionClassifier: Classifies parent chunks by semantic section type.

Identifies document sections like Executive Summary, Findings, Recommendations,
Annexures, etc. for navigation and analytics.

P1-C: Adds configurable confidence thresholds for low-confidence flagging.
"""

import re
import logging
from typing import List, Dict, Optional
from enum import Enum

from src.core.data_contracts import SectionClassification

logger = logging.getLogger(__name__)


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
    # P0-09: Expanded taxonomy for State/Local Body performance audits
    FINANCIAL_MANAGEMENT = "financial_management"
    EMPLOYMENT = "employment"
    EXECUTION = "execution"
    PLANNING = "planning"
    CAPACITY_BUILDING = "capacity_building"
    GRIEVANCE_REDRESSAL = "grievance_redressal"
    IMPACT = "impact"
    MONITORING_EVALUATION = "monitoring_evaluation"
    COMPLIANCE_REVIEW = "compliance_review"
    PERFORMANCE_AUDIT = "performance_audit"
    INFRASTRUCTURE = "infrastructure"
    SERVICE_DELIVERY = "service_delivery"
    REGULATORY = "regulatory"
    ENVIRONMENT = "environment"
    OTHER = "other"


class SectionClassifier:
    """
    Classifies parent chunks by section type using pattern matching.

    Uses hierarchy context and ToC titles to determine section semantics.
    """

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
        # P0-09: Expanded patterns for State/Local Body performance audits
        SectionType.FINANCIAL_MANAGEMENT: [
            r"financial\s+management",
            r"fund\s+(?:management|utilization|utili[sz]ation)",
            r"budgetary\s+(?:control|management)",
            r"financial\s+(?:control|oversight|irregularities)",
            r"expenditure\s+management",
            r"resource\s+management",
            r"budget\s+(?:execution|implementation)",
        ],
        SectionType.EMPLOYMENT: [
            r"employment\s+(?:generation|pattern|opportunities)",
            r"wages?\s+(?:payment|distribution|disbursement)",
            r"labour\s+(?:engagement|deployment|management)",
            r"manpower\s+(?:management|deployment|planning)",
            r"human\s+resource",
            r"staff(?:ing)?\s+(?:position|pattern|strength)",
            r"man[\s-]?days?\s+(?:generation|employment)",
        ],
        SectionType.EXECUTION: [
            r"execution\s+of\s+(?:the\s+)?(?:works?|projects?|schemes?)",
            r"implementation\s+of\s+(?:the\s+)?(?:works?|projects?|schemes?|programmes?)",
            r"project\s+(?:execution|implementation)",
            r"works?\s+(?:execution|management)",
            r"construction\s+(?:of|activities)",
            r"contract\s+(?:management|execution)",
        ],
        SectionType.PLANNING: [
            r"planning\s+(?:and\s+)?(?:implementation|execution)",
            r"deficiencies\s+in\s+planning",
            r"project\s+planning",
            r"action\s+plan",
            r"perspective\s+plan",
            r"annual\s+(?:action\s+)?plan",
            r"master\s+plan",
            r"planning\s+process",
        ],
        SectionType.CAPACITY_BUILDING: [
            r"capacity\s+building",
            r"training\s+(?:and\s+)?(?:capacity|development)",
            r"skill\s+(?:development|training)",
            r"institutional\s+(?:strengthening|capacity)",
            r"human\s+resource\s+development",
        ],
        SectionType.GRIEVANCE_REDRESSAL: [
            r"grievance\s+(?:redressal|redress|handling)",
            r"complaint\s+(?:handling|redressal|mechanism)",
            r"public\s+grievance",
            r"citizen\s+(?:grievance|complaint)",
            r"redressal\s+mechanism",
        ],
        SectionType.IMPACT: [
            r"impact\s+(?:assessment|analysis|evaluation)",
            r"outcome\s+(?:assessment|analysis|evaluation)",
            r"socio[\s-]?economic\s+impact",
            r"environmental\s+impact",
            r"achievement\s+of\s+(?:objectives?|outcomes?|goals?)",
            r"impact\s+on\s+(?:beneficiaries|community|society)",
        ],
        SectionType.MONITORING_EVALUATION: [
            r"monitoring\s+(?:and\s+)?(?:evaluation|review)",
            r"oversight\s+(?:mechanism|system|framework)",
            r"internal\s+(?:audit|control)",
            r"evaluation\s+(?:mechanism|system)",
            r"review\s+(?:mechanism|system)",
            r"supervision\s+(?:and\s+)?(?:monitoring|control)",
            r"inspection\s+(?:mechanism|system)",
            r"performance\s+(?:monitoring|review)",
        ],
        SectionType.COMPLIANCE_REVIEW: [
            r"compliance\s+(?:review|audit|assessment)",
            r"regulatory\s+compliance",
            r"compliance\s+with\s+(?:rules?|guidelines?|provisions?)",
            r"statutory\s+compliance",
            r"compliance\s+status",
        ],
        SectionType.PERFORMANCE_AUDIT: [
            r"performance\s+(?:audit|review)",
            r"efficiency\s+(?:audit|review)",
            r"effectiveness\s+(?:audit|review)",
            r"economy\s+(?:audit|review)",
            r"value[\s-]?for[\s-]?money",
        ],
        SectionType.INFRASTRUCTURE: [
            r"infrastructure\s+(?:development|creation|management)",
            r"physical\s+infrastructure",
            r"basic\s+(?:infrastructure|facilities|amenities)",
            r"(?:road|bridge|building|water\s+supply)\s+(?:infrastructure|works?)",
            r"solid\s+waste\s+management",
            r"sanitation\s+(?:and\s+)?(?:infrastructure|facilities)",
            r"drainage\s+(?:and\s+)?(?:infrastructure|system)",
        ],
        SectionType.SERVICE_DELIVERY: [
            r"service\s+delivery",
            r"delivery\s+of\s+(?:services?|benefits?)",
            r"public\s+service",
            r"citizen\s+service",
            r"service\s+(?:provision|provisioning)",
            r"benefit\s+(?:delivery|disbursement|distribution)",
        ],
        SectionType.REGULATORY: [
            r"regulatory\s+(?:framework|mechanism|compliance)",
            r"regulation\s+(?:and\s+)?(?:enforcement|compliance)",
            r"licensing\s+(?:and\s+)?(?:regulation|control)",
            r"enforcement\s+(?:mechanism|activities)",
        ],
        SectionType.ENVIRONMENT: [
            r"environment(?:al)?\s+(?:management|protection|compliance)",
            r"pollution\s+(?:control|prevention|management)",
            r"environmental\s+(?:clearance|compliance|safeguards)",
            r"ecology\s+(?:and\s+)?environment",
            r"climate\s+change",
            r"forest\s+(?:conservation|management)",
        ],
    }

    # P1-C: Default confidence threshold for classification acceptance
    DEFAULT_CONFIDENCE_THRESHOLD = 0.5

    def __init__(self, confidence_threshold: Optional[float] = None):
        """
        Initialize with compiled regex patterns.

        Args:
            confidence_threshold: Minimum confidence to accept classification.
                                 Below this, section is classified as OTHER.
                                 Default: 0.5 (from config or class default)
        """
        self._section_type_patterns = {
            st: [re.compile(p, re.IGNORECASE) for p in patterns]
            for st, patterns in self.SECTION_TYPE_PATTERNS.items()
        }

        # P1-C: Load threshold from config or use provided/default
        if confidence_threshold is not None:
            self._confidence_threshold = confidence_threshold
        else:
            try:
                from src.parsing_pipeline.modules.enrichment.pattern_loader import get_pattern_loader
                thresholds = get_pattern_loader().get_confidence_thresholds()
                self._confidence_threshold = thresholds.get(
                    "section_classification", self.DEFAULT_CONFIDENCE_THRESHOLD
                )
            except Exception:
                self._confidence_threshold = self.DEFAULT_CONFIDENCE_THRESHOLD

        logger.debug(f"SectionClassifier initialized with confidence_threshold={self._confidence_threshold}")

    def classify_sections(
        self, parent_chunks: List[Dict]
    ) -> List[SectionClassification]:
        """
        Classify parent chunks by section type.

        P1-C: Classifications below confidence threshold are marked as OTHER
        with is_low_confidence=True for potential LLM validation.

        Args:
            parent_chunks: List of parent chunk dicts

        Returns:
            List of SectionClassification objects
        """
        classifications = []
        low_confidence_count = 0

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
            is_low_confidence = False

            for section_type, patterns in self._section_type_patterns.items():
                for pattern in patterns:
                    if pattern.search(full_context):
                        # Higher confidence for exact title match
                        confidence = 0.9 if pattern.search(section_title) else 0.7
                        if confidence > best_confidence:
                            best_type = section_type
                            best_confidence = confidence

            # P1-C: Apply confidence threshold
            # If we found a match but it's below threshold, mark as low confidence
            if best_type != SectionType.OTHER and best_confidence < self._confidence_threshold:
                is_low_confidence = True
                low_confidence_count += 1
                # Keep the classification but flag it for potential review
                # (Don't force to OTHER - let LLM validation decide)

            # If no match found at all, confidence stays 0.0 (OTHER)
            if best_confidence == 0.0:
                best_type = SectionType.OTHER

            classifications.append(
                SectionClassification(
                    chunk_id=chunk.get("chunk_id", ""),
                    section_title=section_title,
                    section_type=best_type.value,
                    confidence=best_confidence,
                    is_low_confidence=is_low_confidence,  # P1-C: Flag for LLM validation
                )
            )

        if low_confidence_count > 0:
            logger.debug(
                f"Section classification: {low_confidence_count}/{len(parent_chunks)} "
                f"sections flagged as low confidence (threshold={self._confidence_threshold})"
            )

        return classifications
