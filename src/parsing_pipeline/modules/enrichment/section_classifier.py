"""
SectionClassifier: Classifies parent chunks by semantic section type.

section_type is the section's role in the report: front matter, preface,
executive summary, introduction (and its audit objectives, scope, criteria and
methodology), findings, recommendations, conclusion, annexure, glossary.
It comes from three sources:
- position: the level-1 heading a section sits under (an executive summary, an
  introductory "Chapter 1 Introduction / Profile ..." chapter, a body chapter,
  the appendices) and where that heading falls in the report;
- the section's own title ("2.4 Conclusion", "Recommendation 3.1 ...");
- its text, when the children are given ("Audit observed ...").
Confidence says how many of these agree; is_low_confidence marks sections where
they disagree or none applies.

The topic ("financial_management", "monitoring_evaluation", ...) is a separate
tag, from the title patterns that used to decide the type.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
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
    FRONT_MATTER = "front_matter"
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
    Classifies parent chunks by section role, from the contents hierarchy, the
    title and (when given) the text of the section's children.
    """

    # Topical tags, a secondary label next to the role
    TOPIC_PATTERNS = {
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

    # Level-1 headings that decide the role of everything under them
    _L1_ROLES = [
        (
            SectionType.FRONT_MATTER,
            re.compile(
                r"^\W*(?:front\s+matter|(?:table\s+of\s+)?contents|title\s+page|cover|government\s+of\b|"
                r"report\s+of\s+the\s+comptroller|binder\d*|.*\.pdf$|\d+\.?\s+(?:toc|cover|front\s+page|blank\s+page))",
                re.I,
            ),
        ),
        (SectionType.PREFACE, re.compile(r"^\W*(?:preface|foreword|prefatory)", re.I)),
        (
            SectionType.EXECUTIVE_SUMMARY,
            re.compile(
                r"^\W*\d*\W*(?:executive\s+summary|overview\W*$|highlights?\W*$|key\s+(?:audit\s+)?findings|"
                r"summary\s+of\s+(?:audit\s+)?findings|audit\s+summary|"
                r"what\s+(?:the|this)\s+(?:performance\s+)?audit\s+(?:report\s+)?says)",
                re.I,
            ),
        ),
        (
            SectionType.ANNEXURE,
            re.compile(
                r"^\W*(?:list\s+of\s+)?(?:annexures?|appendix|appendices|annex)\b", re.I
            ),
        ),
        (
            SectionType.GLOSSARY,
            re.compile(
                r"^\W*(?:glossary|(?:list\s+of\s+)?abbreviations|acronyms)", re.I
            ),
        ),
        (SectionType.ACKNOWLEDGEMENT, re.compile(r"^\W*acknowledge?ments?", re.I)),
    ]

    # A chapter heading: "Chapter III ...", "CHAPTER-2 ...", "3. Planning ..."
    _CHAPTER = re.compile(r"^\W*(?:chapter\b|\d{1,2}\.?\s+[A-Za-z])", re.I)
    _INTRO_CHAPTER = re.compile(
        r"\b(?:introduction|profile|background|overview|about\s+the|general)\b", re.I
    )
    _CONCLUSION_CHAPTER = re.compile(r"\b(?:conclusions?|concluding\s+remarks)\b", re.I)
    _RECOMMENDATION_CHAPTER = re.compile(
        r"\b(?:summary\s+of\s+)?recommendations\b", re.I
    )

    # The section's own title (number prefix allowed)
    _NUM = r"^\W*(?:\d+(?:\.\d+)*\.?\s*)?"
    _TITLE_ROLES = [
        (
            SectionType.CONCLUSION,
            re.compile(
                _NUM
                + r"(?:conclusions?|concluding\s+remarks|summary\s+and\s+conclusions?)\b",
                re.I,
            ),
        ),
        (
            SectionType.RECOMMENDATIONS,
            re.compile(
                _NUM
                + r"(?:(?:audit\s+|summary\s+of\s+)?recommendations?\b|what\s+do\s+we\s+recommend)",
                re.I,
            ),
        ),
        (SectionType.ACKNOWLEDGEMENT, re.compile(_NUM + r"acknowledge?ments?\b", re.I)),
        (
            SectionType.AUDIT_OBJECTIVES,
            re.compile(
                _NUM
                + r"(?:audit\s+objectives?|objectives?\s+of\s+(?:the\s+)?(?:performance\s+)?audit)",
                re.I,
            ),
        ),
        (
            SectionType.AUDIT_SCOPE,
            re.compile(
                _NUM
                + r"(?:(?:audit\s+)?scope|audit\s+coverage|coverage\s+of\s+audit|audit\s+sampl|sampling)",
                re.I,
            ),
        ),
        (
            SectionType.AUDIT_CRITERIA,
            re.compile(
                _NUM
                + r"(?:(?:sources?\s+of\s+)?audit\s+criteria|criteria\s+for\s+audit)",
                re.I,
            ),
        ),
        (
            SectionType.AUDIT_METHODOLOGY,
            re.compile(_NUM + r"(?:audit\s+)?(?:methodology|approach)\b", re.I),
        ),
        (
            SectionType.INTRODUCTION,
            re.compile(_NUM + r"(?:introduction|background)\b", re.I),
        ),
        (
            SectionType.GLOSSARY,
            re.compile(_NUM + r"(?:glossary|abbreviations)\b", re.I),
        ),
        (
            SectionType.FINDINGS,
            re.compile(
                _NUM + r"(?:(?:audit|detailed)\s+findings|audit\s+observations)\b", re.I
            ),
        ),
    ]

    # Text cues in a section's children
    _FINDING_TEXT = re.compile(
        r"\b(?:audit\s+(?:observed|noticed|found|noted)|it\s+was\s+(?:observed|noticed|found)|"
        r"test[\s-]check(?:ed)?\b[^.]{0,80}\b(?:revealed|showed|disclosed)|scrutiny\s+of\b[^.]{0,80}\brevealed)",
        re.I,
    )
    _RECOMMENDATION_TEXT = re.compile(
        r"^\W*(?:recommendations?\s*(?:\d|:|-)|(?:audit|we)\s+recommends?\b)", re.I
    )

    # Roles a level-1 region hands to every section under it
    _REGION_ROLES = {
        SectionType.FRONT_MATTER,
        SectionType.PREFACE,
        SectionType.EXECUTIVE_SUMMARY,
        SectionType.ANNEXURE,
        SectionType.GLOSSARY,
        SectionType.ACKNOWLEDGEMENT,
    }

    # P1-C: Default confidence threshold for classification acceptance
    DEFAULT_CONFIDENCE_THRESHOLD = 0.5

    def __init__(self, confidence_threshold: Optional[float] = None):
        """
        Initialize with compiled regex patterns.

        Args:
            confidence_threshold: Below this confidence a section is flagged
                                 is_low_confidence. Default: 0.5 (from config or class default)
        """
        self._topic_patterns = {
            st: [re.compile(p, re.IGNORECASE) for p in patterns]
            for st, patterns in self.TOPIC_PATTERNS.items()
        }

        # P1-C: Load threshold from config or use provided/default
        if confidence_threshold is not None:
            self._confidence_threshold = confidence_threshold
        else:
            try:
                from src.parsing_pipeline.modules.enrichment.pattern_loader import (
                    get_pattern_loader,
                )

                thresholds = get_pattern_loader().get_confidence_thresholds()
                self._confidence_threshold = thresholds.get(
                    "section_classification", self.DEFAULT_CONFIDENCE_THRESHOLD
                )
            except Exception:
                self._confidence_threshold = self.DEFAULT_CONFIDENCE_THRESHOLD

        logger.debug(
            f"SectionClassifier initialized with confidence_threshold={self._confidence_threshold}"
        )

    def classify_topic(self, title: str) -> Optional[str]:
        """The topical tag of a section title, or None."""
        for section_type, patterns in self._topic_patterns.items():
            if any(p.search(title or "") for p in patterns):
                return section_type.value
        return None

    def _l1_role(self, title: str, seen_chapter: bool) -> Tuple[SectionType, float]:
        """(role, confidence) of a level-1 heading."""
        for role, pattern in self._L1_ROLES:
            if pattern.search(title):
                return role, 0.9
        if self._CHAPTER.match(title) or seen_chapter:
            confidence = 0.8 if self._CHAPTER.match(title) else 0.6
            if self._CONCLUSION_CHAPTER.search(title):
                return SectionType.CONCLUSION, confidence
            if self._RECOMMENDATION_CHAPTER.match(
                re.sub(r"^\W*chapter\W*\w+\W*", "", title, flags=re.I)
            ):
                return SectionType.RECOMMENDATIONS, confidence
            if self._INTRO_CHAPTER.search(title):
                return SectionType.INTRODUCTION, confidence
            return SectionType.FINDINGS, confidence
        return SectionType.OTHER, 0.3

    def classify_sections(
        self, parent_chunks: List[Dict], child_chunks: Optional[List[Dict]] = None
    ) -> List[SectionClassification]:
        """
        Classify parent chunks by section role.

        Args:
            parent_chunks: List of parent chunk dicts, in document order
            child_chunks: Optional child chunks; their text adds the content cues

        Returns:
            List of SectionClassification objects
        """
        finding_cues: Dict[str, int] = {}
        rec_cues: Dict[str, int] = {}
        for child in child_chunks or []:
            pid = child.get("parent_chunk_id")
            content = child.get("content") or ""
            if self._FINDING_TEXT.search(content):
                finding_cues[pid] = finding_cues.get(pid, 0) + 1
            if self._RECOMMENDATION_TEXT.search(content):
                rec_cues[pid] = rec_cues.get(pid, 0) + 1

        # Roles of the level-1 regions, in document order
        l1_roles: Dict[str, Tuple[SectionType, float]] = {}
        seen_chapter = False
        for chunk in parent_chunks:
            title = (chunk.get("toc_entry") or "").strip()
            level_1 = ((chunk.get("hierarchy") or {}).get("level_1") or title).strip()
            if level_1 in l1_roles:
                continue
            role, confidence = self._l1_role(level_1, seen_chapter)
            l1_roles[level_1] = (role, confidence)
            if role in (
                SectionType.INTRODUCTION,
                SectionType.FINDINGS,
            ) and self._CHAPTER.match(level_1):
                seen_chapter = True

        with_topic = "topic" in getattr(SectionClassification, "model_fields", {})
        classifications = []
        low_confidence_count = 0

        for chunk in parent_chunks:
            chunk_id = chunk.get("chunk_id", "")
            section_title = chunk.get("toc_entry", "") or ""
            title = section_title.strip()
            level_1 = ((chunk.get("hierarchy") or {}).get("level_1") or title).strip()
            region, region_conf = l1_roles.get(level_1, (SectionType.OTHER, 0.3))
            title_role = next((r for r, p in self._TITLE_ROLES if p.match(title)), None)
            has_findings = finding_cues.get(chunk_id, 0) > 0
            has_recs = rec_cues.get(chunk_id, 0) > 0

            if region in self._REGION_ROLES:
                # The executive summary, appendices, preface: every section under them
                role, confidence = region, (region_conf if title == level_1 else 0.85)
            elif title_role is not None:
                role, confidence = title_role, 0.9
                if title_role == SectionType.FINDINGS and region == SectionType.OTHER:
                    confidence = 0.7
            elif region == SectionType.OTHER:
                # No chapter structure: the text decides, weakly
                if has_recs and not has_findings:
                    role, confidence = SectionType.RECOMMENDATIONS, 0.55
                elif has_findings:
                    role, confidence = SectionType.FINDINGS, 0.55
                else:
                    role, confidence = SectionType.OTHER, 0.3
            elif title == level_1:
                role, confidence = region, region_conf
            else:
                role = region
                if region == SectionType.FINDINGS:
                    # A body section: its text should say what audit found
                    confidence = 0.85 if has_findings else (0.7 if has_recs else 0.6)
                    if has_recs and not has_findings and rec_cues[chunk_id] >= 2:
                        role, confidence = SectionType.RECOMMENDATIONS, 0.6
                elif region == SectionType.INTRODUCTION:
                    # Introductory chapters describe; several audit observations disagree
                    confidence = 0.45 if finding_cues.get(chunk_id, 0) >= 2 else 0.75
                else:
                    confidence = region_conf

            is_low_confidence = confidence < self._confidence_threshold
            if is_low_confidence:
                low_confidence_count += 1

            fields = dict(
                chunk_id=chunk_id,
                section_title=section_title,
                section_type=role.value,
                confidence=round(confidence, 2),
                is_low_confidence=is_low_confidence,
            )
            if with_topic:
                fields["topic"] = self.classify_topic(title)
            classifications.append(SectionClassification(**fields))

        if low_confidence_count > 0:
            logger.debug(
                f"Section classification: {low_confidence_count}/{len(parent_chunks)} "
                f"sections flagged as low confidence (threshold={self._confidence_threshold})"
            )

        return classifications
