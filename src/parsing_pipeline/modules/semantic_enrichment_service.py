"""
SemanticEnrichmentService: Orchestrates CAG-specific semantic tagging and entity extraction.

This slim orchestrator coordinates multiple focused extractors:
- FindingExtractor: Audit findings with monetary values and severity
- EntityExtractor: Schemes, ministries, organizations
- SectionClassifier: Section type classification
- BoxElementExtractor: Box X.X illustrative elements
- RecommendationExtractor: Multi-strategy recommendation extraction (existing)
- TemporalExtractor: Temporal metadata (existing)
- AnnexureLinker: Annexure cross-references (existing)
- CrossReferenceResolver: Cross-chunk references (existing)

Enables cross-report analytics queries like:
- "Top 10 largest irregular expenditures across all reports"
- "Which ministry has the most pending recommendations?"
- "Compare audit findings in Railways 2023 vs 2024"
"""

import logging
import re
from typing import TYPE_CHECKING, List, Dict, Optional, Any

if TYPE_CHECKING:
    from src.parsing_pipeline.instrumentation import TraceEmitter


PAISE_PER_CRORE = 1_000_000_000

# Leading paragraph number of a section heading ("3.2.1 Delay in ..."), and content words
_SECTION_NO = re.compile(r"\s*(\d+(?:\.\d+)+)")
_WORD = re.compile(r"[a-z]{4,}")

logger = logging.getLogger(__name__)

# Core data contracts
from src.core.data_contracts import (
    DocumentTask,
    Finding,
    Recommendation,
    SectionClassification,
    SemanticEnrichment,
)

# Report type detection
from src.parsing_pipeline.modules import report_type_profiles

# Focused extractors (new)
from src.parsing_pipeline.modules.enrichment.finding_extractor import (
    FindingExtractor,
    FindingType,
    Severity,
)
from src.parsing_pipeline.modules.enrichment.entity_extractor import EntityExtractor
from src.parsing_pipeline.modules.enrichment.section_classifier import (
    SectionClassifier,
    SectionType,
)
from src.parsing_pipeline.modules.enrichment.box_element_extractor import BoxElementExtractor

# Existing enrichment modules (unchanged)
from src.parsing_pipeline.modules.enrichment.recommendation_extractor import (
    RecommendationExtractor,
)
from src.parsing_pipeline.modules.enrichment.temporal_extractor import TemporalExtractor
from src.parsing_pipeline.modules.enrichment.annexure_linker import AnnexureLinker
from src.parsing_pipeline.modules.enrichment.cross_reference_resolver import (
    CrossReferenceResolver,
)
from src.parsing_pipeline.modules.enrichment.executive_summary_parser import (
    ExecutiveSummaryParser,
)

# Evidence linker (in parent directory)
from src.parsing_pipeline.modules import evidence_linker

# Findings and recommendations from Gemini (calls made by the orchestrator)
from src.parsing_pipeline.modules.enrichment import llm_finding_extractor


class SemanticEnrichmentService:
    """
    Enriches parsed CAG documents with semantic tags and extracted entities.

    Orchestrates extraction of:
    1. Findings - Audit observations with monetary impact
    2. Recommendations - Action items for ministries
    3. Section Classifications - Semantic section tagging
    4. Entities - Schemes, ministries, organizations
    5. Box Elements - Illustrative boxes
    6. Temporal Coverage - Audit periods and reference years
    7. Cross-References - Annexure and paragraph references
    """

    def __init__(self):
        """Initialize all extractors."""
        # New focused extractors
        self._finding_extractor = FindingExtractor()
        self._entity_extractor = EntityExtractor()
        self._section_classifier = SectionClassifier()
        self._box_extractor = BoxElementExtractor()

        # Existing extractors
        self._rec_extractor = RecommendationExtractor()
        self._temporal_extractor = TemporalExtractor()
        self._annexure_linker = AnnexureLinker()
        self._xref_resolver = CrossReferenceResolver()
        self._evidence_linker = evidence_linker.EvidenceLinker()

        # Current report type (set per document)
        self._current_report_type = "general"

    def enrich_document(
        self,
        report_id: str,
        report_metadata: Dict,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        task: Optional[DocumentTask] = None,
        trace_emitter: Optional["TraceEmitter"] = None,
        llm_extraction: Optional[Dict[str, Any]] = None,
    ) -> SemanticEnrichment:
        """
        Run all enrichment extractions on a document.

        Args:
            report_id: Unique report identifier
            report_metadata: Report metadata dict
            parent_chunks: List of parent chunk dicts
            child_chunks: List of child chunk dicts
            task: Optional DocumentTask for report type detection
            trace_emitter: Optional trace emitter for instrumentation
            llm_extraction: The Gemini items for this report (llm_finding_extractor.
                extraction_record). Without it, findings and recommendations come
                from the regex extractors alone.

        Returns:
            SemanticEnrichment object with all extracted data
        """
        # Use no-op emitter if none provided
        if trace_emitter is None:
            from src.parsing_pipeline.instrumentation import get_noop_emitter
            trace_emitter = get_noop_emitter()

        logger.info(f"Enriching document: {report_id}")

        # Detect report type for type-aware extraction
        if task:
            self._current_report_type = report_type_profiles.detect_report_type(task)
        else:
            self._current_report_type = report_type_profiles.normalize_report_type(
                report_metadata.get("report_type", "general")
            )
        logger.info(f"  Detected report type: {self._current_report_type}")

        # 1. Classify sections (with error handling - P1-A)
        try:
            section_classifications = self._section_classifier.classify_sections(
                parent_chunks
            )
            logger.info(f"  Classified {len(section_classifications)} sections")
        except Exception as e:
            logger.warning(f"  Section classification failed: {e}")
            section_classifications = []
            trace_emitter.emit_red_flag(
                "9", "section_classifier_failed",
                {"error": str(e), "report_id": report_id}
            )

        # 2-3. Findings and recommendations: Gemini items checked against the text,
        # regex for any section whose call failed, regex everywhere without Gemini
        government_body_type = report_metadata.get("government_body_type", "union")
        findings, recommendations, extraction_stats = self._extract_findings_and_recommendations(
            report_id,
            parent_chunks,
            child_chunks,
            section_classifications,
            government_body_type,
            llm_extraction,
            trace_emitter,
        )
        for finding in findings:
            try:
                finding.entities_mentioned = self._entity_extractor.extract_entities_from_text(
                    finding.text
                )
            except Exception as entity_err:
                logger.warning(f"  Entity extraction for finding failed: {entity_err}")
                finding.entities_mentioned = []
        logger.info(
            f"  Extracted {len(findings)} findings, {len(recommendations)} recommendations "
            f"({extraction_stats.get('method')})"
        )

        # 4. Link findings to recommendations (with error handling - P1-A)
        try:
            self._link_findings_to_recommendations(findings, recommendations)
        except Exception as e:
            logger.warning(f"  Finding-recommendation linking failed: {e}")

        # 5. Create evidence links for findings (with error handling - P1-A)
        try:
            evidence_links_map = self._link_evidence_to_findings(findings, child_chunks)
            logger.info(f"  Created evidence links for {len(evidence_links_map)} findings")
        except Exception as e:
            logger.warning(f"  Evidence linking failed: {e}")
            evidence_links_map = {}

        # 5b. Link findings to annexures (with error handling - P1-A)
        try:
            annexure_links = self._annexure_linker.link_annexures(
                child_chunks,
                parent_chunks,
                [f.model_dump() for f in findings],
            )
            resolved = sum(1 for link in annexure_links if link["resolved"])
            logger.info(f"  Annexure links: {len(annexure_links)} references, {resolved} resolved")
        except Exception as e:
            logger.warning(f"  Annexure linking failed: {e}")
            annexure_links = []

        # 6. Extract entities (with error handling - P1-A)
        try:
            entities = self._entity_extractor.extract_entities(child_chunks)
            logger.info(
                f"  Extracted entities: {', '.join(f'{k}={len(v)}' for k, v in entities.items())}"
            )
        except Exception as e:
            logger.warning(f"  Entity extraction failed: {e}")
            entities = {"schemes": [], "ministries": [], "organizations": []}
            trace_emitter.emit_red_flag(
                "9", "entity_extractor_failed",
                {"error": str(e), "report_id": report_id}
            )

        # 6b. Detect box elements (with error handling - P1-A)
        try:
            box_elements = self._box_extractor.detect_box_elements(child_chunks)
            if box_elements:
                logger.info(f"  Detected {len(box_elements)} box elements")
        except Exception as e:
            logger.warning(f"  Box element detection failed: {e}")
            box_elements = []

        # 6c. Parse executive summary (with error handling - P1-A)
        try:
            exec_parser = ExecutiveSummaryParser()
            exec_summary_index = exec_parser.parse_executive_summary(
                parent_chunks,
                child_chunks,
                [s.model_dump() for s in section_classifications],
            )
            if exec_summary_index:
                logger.info(
                    f"  Exec summary: {exec_summary_index['total_items']} items, "
                    f"{exec_summary_index['resolution_rate']*100:.0f}% citations resolved"
                )
        except Exception as e:
            logger.warning(f"  Executive summary parsing failed: {e}")
            exec_summary_index = None

        # 7. Extract temporal metadata (with error handling - P1-A)
        # P2-21: Pass report_year to filter future years
        report_year = report_metadata.get("report_year")
        try:
            temporal_coverage = self._temporal_extractor.extract_temporal_metadata(
                child_chunks,
                [s.model_dump() for s in section_classifications],
                report_year=report_year,
            )
            logger.info(
                f"  Temporal: audit_period={temporal_coverage.get('audit_period')}, "
                f"ref_years={len(temporal_coverage.get('reference_years', []))}"
            )

            # Annotate findings with temporal context
            for finding in findings:
                try:
                    # P2-21: Pass report_year for future year filtering
                    finding.reference_years = self._temporal_extractor.extract_reference_years(
                        finding.text, report_year=report_year
                    )
                    if temporal_coverage.get("audit_period"):
                        finding.audit_period = temporal_coverage["audit_period"]
                except Exception as temp_err:
                    logger.warning(f"  Temporal annotation for finding failed: {temp_err}")
        except Exception as e:
            logger.warning(f"  Temporal extraction failed: {e}")
            temporal_coverage = {"audit_period": None, "reference_years": [], "previous_audit_refs": []}
            trace_emitter.emit_red_flag(
                "9", "temporal_extractor_failed",
                {"error": str(e), "report_id": report_id}
            )

        # 8. Resolve cross-chunk references (with error handling - P1-A)
        try:
            cross_references = self._xref_resolver.resolve_references(
                child_chunks, parent_chunks
            )
            resolved_xrefs = sum(1 for x in cross_references if x["resolved"])
            logger.info(
                f"  Cross-references: {len(cross_references)} found, {resolved_xrefs} resolved"
            )
        except Exception as e:
            logger.warning(f"  Cross-reference resolution failed: {e}")
            cross_references = []

        # 9. Calculate statistics (includes report type)
        statistics = self._calculate_statistics(
            report_metadata, findings, recommendations, section_classifications, child_chunks
        )
        statistics["extraction"] = extraction_stats

        # Emit Phase 9 trace events
        with trace_emitter.phase_timer("9"):
            # Finding type distribution
            finding_type_dist = {}
            for f in findings:
                ft = f.finding_type if hasattr(f, "finding_type") else "unknown"
                finding_type_dist[ft] = finding_type_dist.get(ft, 0) + 1

            # Check for high "other" findings (red flag if >30%)
            other_count = finding_type_dist.get("other", 0)

            # C1 fix: Guard against impossible other_count > total_findings
            # This would indicate a counting bug in finding_extractor
            if other_count > len(findings):
                trace_emitter.emit_red_flag(
                    "9",
                    "finding_other_count_inflation",
                    {
                        "other_count": other_count,
                        "total_findings": len(findings),
                        "note": "Bug: other_count exceeds total findings - check finding_extractor",
                    },
                )
                # Cap to prevent >100% calculation
                other_count = len(findings)

            # D6: Report-type-aware thresholds
            OTHER_RATIO_THRESHOLDS = {
                "compliance": 0.30,
                "performance": 0.30,
                "financial": 0.50,      # Financial audits have many accounting misstatements
                "atir": 0.40,
                "state_commercial": 0.35,
                "state_performance": 0.30,
                "general": 0.40,
            }

            # D6: Minimum finding count (small samples are noise)
            MIN_FINDINGS_FOR_RATIO_CHECK = 10

            threshold = OTHER_RATIO_THRESHOLDS.get(self._current_report_type, 0.40)

            if (findings
                and len(findings) >= MIN_FINDINGS_FOR_RATIO_CHECK
                and other_count / len(findings) > threshold):
                trace_emitter.emit_red_flag(
                    "9",
                    "finding_other_ratio_high",
                    {
                        "other_count": other_count,
                        "total_findings": len(findings),
                        "ratio": round(other_count / len(findings), 3),
                        "threshold": threshold,
                        "report_type": self._current_report_type,
                    },
                )

            # P0-01: Check for implausibly large monetary totals
            # C3 fix: Report-type thresholds first, then tier-based fallback
            # Aggregate report types (financial, compliance) cover many transactions
            REPORT_TYPE_THRESHOLDS = {
                "financial": 10_000_000,   # ₹100 lakh crore - State Finance aggregates
                "compliance": 5_000_000,   # ₹50 lakh crore - broad transaction audits
                "revenue": 5_000_000,      # ₹50 lakh crore - tax/revenue collection audits
            }
            # Tier-specific fallback thresholds (for performance, commercial, etc.)
            TIER_THRESHOLDS = {
                "union": 500_000,      # ₹5 lakh crore
                "state": 100_000,      # ₹1 lakh crore
                "local_body": 10_000,  # ₹10,000 crore
            }
            total_monetary_crore = statistics.get("findings", {}).get("impact_sum_crore", 0)
            detected_report_type = self._current_report_type

            # C3 fix: Use report-type threshold if available, else tier-based
            if detected_report_type in REPORT_TYPE_THRESHOLDS:
                threshold = REPORT_TYPE_THRESHOLDS[detected_report_type]
                threshold_source = f"report_type:{detected_report_type}"
            else:
                threshold = TIER_THRESHOLDS.get(government_body_type, 500_000)
                threshold_source = f"tier:{government_body_type}"

            if total_monetary_crore > threshold:
                trace_emitter.emit_red_flag(
                    "9",
                    "monetary_total_implausible",
                    {
                        "total_monetary_crore": total_monetary_crore,
                        "threshold_crore": threshold,
                        "threshold_source": threshold_source,  # C3: report_type:X or tier:Y
                        "detected_report_type": detected_report_type,
                        "government_body_type": government_body_type,
                        "ratio_to_threshold": round(total_monetary_crore / threshold, 2),
                    },
                )

            # Tier-specific severity threshold decision
            trace_emitter.emit_decision(
                "9",
                "severity_threshold_tier",
                government_body_type,
                ["union", "state", "local_body"],
                f"Using {government_body_type} severity thresholds: "
                f"critical={'100 crore' if government_body_type == 'union' else '50 crore' if government_body_type == 'state' else '10 crore'}",
            )

            # Section classification distribution
            section_type_counts = {}
            for s in section_classifications:
                st = s.section_type if hasattr(s, "section_type") else str(s.get("section_type", "unknown"))
                section_type_counts[st] = section_type_counts.get(st, 0) + 1
            trace_emitter.emit_sample(
                "9",
                "section_classifications",
                [{"type": k, "count": v} for k, v in section_type_counts.items()],
            )

            # P0-09: Check for high 'other' section ratio (red flag if >70%)
            section_other_count = section_type_counts.get("other", 0)
            if section_classifications and section_other_count / len(section_classifications) > 0.70:
                trace_emitter.emit_red_flag(
                    "9",
                    "section_other_ratio_high",
                    {
                        "other_count": section_other_count,
                        "total_sections": len(section_classifications),
                        "percentage": round(section_other_count / len(section_classifications) * 100, 1),
                    },
                )

            # Box elements count
            if box_elements:
                trace_emitter.emit_sample(
                    "9",
                    "box_elements",
                    [{"box_id": b.get("box_id", f"box_{i}"), "title": b.get("title", "")[:50]}
                     for i, b in enumerate(box_elements[:5])],
                )

            # Executive summary parsed
            if exec_summary_index:
                trace_emitter.emit_io(
                    "9",
                    {"exec_summary_parsing": True},
                    {
                        "total_items": exec_summary_index.get("total_items", 0),
                        "resolution_rate": exec_summary_index.get("resolution_rate", 0),
                        "sections_found": len(exec_summary_index.get("sections", [])),
                    },
                )

            # Emit main I/O summary
            trace_emitter.emit_io(
                "9",
                {
                    "parent_chunks": len(parent_chunks),
                    "child_chunks": len(child_chunks),
                    "report_type": self._current_report_type,
                    "government_body_type": government_body_type,
                },
                {
                    "findings": len(findings),
                    "recommendations": len(recommendations),
                    "entities": sum(len(v) for v in entities.values()),
                    "sections_classified": len(section_classifications),
                    "box_elements": len(box_elements) if box_elements else 0,
                    "impact_sum_crore": statistics.get("findings", {}).get("impact_sum_crore", 0),
                },
            )

            # Finding and severity distribution as sample
            trace_emitter.emit_sample(
                "9",
                "finding_distribution",
                [
                    {"category": "by_type", "data": finding_type_dist},
                    {"category": "by_severity", "data": statistics.get("findings", {}).get("by_severity", {})},
                ],
            )

            # Sample findings for inspection
            if findings:
                sample_findings = [
                    {
                        "id": f.finding_id,
                        "type": f.finding_type if hasattr(f, "finding_type") else "unknown",
                        "severity": f.severity if hasattr(f, "severity") else "unknown",
                        "monetary": f.monetary_value_crore if hasattr(f, "monetary_value_crore") else 0,
                        "text_preview": f.text[:100] if f.text else "",
                    }
                    for f in findings[:5]
                ]
                trace_emitter.emit_sample("9", "findings", sample_findings)

            # Recommendation strategy distribution
            rec_strategy_dist = {}
            for r in recommendations:
                strat = r.extraction_strategy if hasattr(r, "extraction_strategy") else "unknown"
                rec_strategy_dist[strat] = rec_strategy_dist.get(strat, 0) + 1
            if rec_strategy_dist:
                trace_emitter.emit_sample(
                    "9",
                    "recommendation_strategies",
                    [{"strategy": k, "count": v} for k, v in rec_strategy_dist.items()],
                )

            trace_emitter.set_phase_status("9", "success")

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
            box_elements=box_elements,
            executive_summary_index=exec_summary_index,
        )

    # ── findings and recommendations ────────────────────────────────────────

    def _regex_findings(
        self, report_id: str, child_chunks: List[Dict], government_body_type: str, parent_chunks: List[Dict]
    ) -> List[Finding]:
        self._finding_extractor.set_report_type(self._current_report_type)
        return self._finding_extractor.extract_findings(
            report_id, child_chunks, government_body_type, parent_chunks
        )

    def _regex_recommendations(
        self,
        report_id: str,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[SectionClassification],
    ) -> List[Recommendation]:
        raw_recs = self._rec_extractor.extract_all(
            report_id,
            parent_chunks,
            child_chunks,
            [s.model_dump() for s in section_classifications],
        )
        return [
            Recommendation(
                recommendation_id=f"{report_id}_rec_{i + 1:03d}",
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
                extraction_strategy=raw.extraction_strategy,
                rec_number=raw.rec_number,
                paragraph_citations=raw.paragraph_citations,
            )
            for i, raw in enumerate(raw_recs)
        ]

    def _extract_findings_and_recommendations(
        self,
        report_id: str,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        section_classifications: List[SectionClassification],
        government_body_type: str,
        llm_extraction: Optional[Dict[str, Any]],
        trace_emitter,
    ):
        """(findings, recommendations, extraction statistics)."""
        try:
            regex_findings = self._regex_findings(report_id, child_chunks, government_body_type, parent_chunks)
        except Exception as e:
            logger.warning(f"  Finding extraction failed: {e}")
            regex_findings = []
            trace_emitter.emit_red_flag("9", "finding_extractor_failed", {"error": str(e), "report_id": report_id})
        try:
            regex_recs = self._regex_recommendations(report_id, parent_chunks, child_chunks, section_classifications)
        except Exception as e:
            logger.warning(f"  Recommendation extraction failed: {e}")
            regex_recs = []
            trace_emitter.emit_red_flag(
                "9", "recommendation_extractor_failed", {"error": str(e), "report_id": report_id}
            )

        if not llm_extraction:
            self._mark_restatements(regex_findings, child_chunks, section_classifications)
            return regex_findings, regex_recs, {"method": "regex"}

        from src.parsing_pipeline.modules.enrichment.llm_items import build_from_llm

        return build_from_llm(
            self,
            report_id,
            parent_chunks,
            child_chunks,
            section_classifications,
            government_body_type,
            llm_extraction,
            regex_findings,
            regex_recs,
            trace_emitter,
        )

    def _mark_restatements(self, findings, child_chunks, section_classifications) -> None:
        from src.parsing_pipeline.modules.enrichment.llm_items import mark_restatements

        mark_restatements(findings, child_chunks, section_classifications)

    def _link_findings_to_recommendations(
        self,
        findings: List[Finding],
        recommendations: List[Recommendation],
    ) -> None:
        """
        Link each recommendation to at most 5 findings (C-9-12).

        Candidates, first non-empty pool wins: findings in the paragraphs the
        recommendation cites (or its number), then findings in the same section at
        any distance, then the same chapter within 5 pages. Ranked by shared words.
        """

        def section_no(text):
            m = _SECTION_NO.match(text or "")
            return m.group(1) if m else None

        def words(text):
            return set(_WORD.findall((text or "").lower()))

        sections = {f.finding_id: section_no(f.section) for f in findings}
        finding_words = {f.finding_id: words(f.text) for f in findings}
        for rec in recommendations:
            cited = list(rec.paragraph_citations or [])
            m = re.search(r"\d+\.\d+(?:\.\d+)*", rec.rec_number or "")
            if m:
                cited.append(m.group(0))
            pool = [
                f for f in findings
                if sections[f.finding_id]
                and any(sections[f.finding_id] == c or sections[f.finding_id].startswith(c + ".") for c in cited)
            ]
            if not pool and rec.section:
                pool = [f for f in findings if f.section and f.section == rec.section]
            if not pool:
                pool = [
                    f for f in findings
                    if rec.chapter and f.chapter == rec.chapter and abs(rec.page - f.page) <= 5
                ]
            rec_words = words(rec.text)
            pool.sort(key=lambda f: len(rec_words & finding_words[f.finding_id]), reverse=True)
            rec.related_finding_ids = [f.finding_id for f in pool[:5]]

    def _link_evidence_to_findings(
        self,
        findings: List[Finding],
        child_chunks: List[Dict],
    ) -> Dict[str, List]:
        """
        Link findings to their supporting evidence.

        Args:
            findings: List of Finding objects
            child_chunks: List of child chunk dicts

        Returns:
            Dict mapping finding_id to list of evidence links
        """
        # Convert findings to dicts for evidence linker
        finding_dicts = [f.model_dump() for f in findings]

        # Extract tables from child_chunks
        tables = [
            chunk for chunk in child_chunks if chunk.get("content_type") == "table"
        ]

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

    def _calculate_statistics(
        self,
        report_metadata: Dict,
        findings: List[Finding],
        recommendations: List[Recommendation],
        sections: List[SectionClassification],
        child_chunks: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Calculate aggregate statistics for the report."""
        # Distinct findings: restatements (executive summary, conclusion) excluded
        distinct = [f for f in findings if not f.is_restatement]
        impact = report_impact(distinct, child_chunks or [], self._section_classifier_types(sections))

        findings_by_type: Dict[str, Dict] = {}
        for f in distinct:
            entry = findings_by_type.setdefault(f.finding_type, {"count": 0, "sum_paise": 0})
            entry["count"] += 1
            entry["sum_paise"] += f.monetary_value_paise or 0
        for entry in findings_by_type.values():
            entry["sum_crore"] = round(entry["sum_paise"] / PAISE_PER_CRORE, 2)
            # Old names, kept until every reader moves over
            entry["total_inr"] = entry["sum_paise"]
            entry["total_crore"] = entry["sum_crore"]

        severity_counts: Dict[str, int] = {}
        for f in findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

        section_type_counts: Dict[str, int] = {}
        for s in sections:
            section_type_counts[s.section_type] = section_type_counts.get(s.section_type, 0) + 1

        target_entity_counts: Dict[str, int] = {}
        for r in recommendations:
            if r.target_entity:
                target_entity_counts[r.target_entity] = target_entity_counts.get(r.target_entity, 0) + 1

        return {
            "report_info": {
                "ministry": report_metadata.get("ministry", "Unknown"),
                "sector": report_metadata.get("sector", "Unknown"),
                "report_type": report_metadata.get("report_type", "Unknown"),
                "detected_report_type": self._current_report_type,
                "publication_date": report_metadata.get("publication_date", "Unknown"),
            },
            "findings": {
                "total_count": len(findings),
                "distinct_count": len(distinct),
                "restatement_count": len(findings) - len(distinct),
                **impact,
                # Old names of the sum, kept as aliases until the full re-run
                "primary_count": len(distinct),
                "total_monetary_inr": impact["impact_sum_paise"],
                "total_monetary_crore": impact["impact_sum_crore"],
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

    @staticmethod
    def _section_classifier_types(sections: List[SectionClassification]) -> Dict[str, str]:
        return {s.chunk_id: s.section_type for s in sections}


_TOTAL_CUE = re.compile(r"\b(?:total(?:ling)?|aggregat\w*|overall|cumulative|in all)\b", re.I)
_IMPACT_CUE = re.compile(
    r"financial implication|money value|monetary (?:value|impact)|irregular|loss|recover|"
    r"wasteful|unfruitful|idle|blocked|excess|short|non-?realisation|non-?realization|avoidable",
    re.I,
)
# A dot between digits ("₹1,234.50") does not end a sentence
_SENTENCE = re.compile(r"(?:[^.;]|\.(?=\d))+(?:[.;]|$)")


def report_impact(
    distinct: List[Finding], child_chunks: List[Dict], parent_types: Dict[str, str]
) -> Dict[str, Any]:
    """
    The report-level money figures. Amounts of different kinds (loss, unspent funds,
    irregular spending) and overlapping findings make any sum something other than
    a "total impact", so the fields say what they are: the sum of the primary amounts
    cited in N distinct findings, the largest single finding, and the total the
    report prints itself (executive summary or overview), when it does.
    """
    with_amount = [f for f in distinct if f.monetary_value_paise]
    impact_sum = sum(f.monetary_value_paise for f in with_amount)
    largest = max(with_amount, key=lambda f: f.monetary_value_paise, default=None)
    out = {
        "impact_sum_paise": impact_sum,
        "impact_sum_crore": round(impact_sum / PAISE_PER_CRORE, 2),
        "impact_sum_finding_count": len(with_amount),
        "largest_finding_id": largest.finding_id if largest else None,
        "largest_finding_paise": largest.monetary_value_paise if largest else None,
        "largest_finding_crore": round(largest.monetary_value_paise / PAISE_PER_CRORE, 2) if largest else None,
        "printed_total_paise": None,
        "printed_total_crore": None,
        "printed_total_text": None,
        "printed_total_source_chunk_id": None,
    }
    printed = printed_total(child_chunks, parent_types)
    if printed:
        out.update(printed)
    return out


def printed_total(child_chunks: List[Dict], parent_types: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    A total the report states itself in its executive summary or overview: a sentence
    with a total cue ("aggregating", "in all") and an impact cue ("irregular",
    "financial implication") and a rupee amount. The largest such amount is kept.
    """
    from src.parsing_pipeline.modules.enrichment.llm_items import chunk_location
    from src.parsing_pipeline.modules.enrichment.monetary_processor import MonetaryProcessor

    mp = MonetaryProcessor()
    best = None
    for chunk in child_chunks:
        if chunk.get("content_type") not in ("paragraph", "list"):
            continue
        if chunk_location(chunk, parent_types) != "executive_summary":
            continue
        for sentence in _SENTENCE.findall(chunk.get("content") or ""):
            if not (_TOTAL_CUE.search(sentence) and _IMPACT_CUE.search(sentence)):
                continue
            values = [v for v in mp.extract_monetary_values_with_preference(sentence) if v.currency == "INR"]
            for v in values:
                if best is None or (v.normalized_paise or 0) > best["printed_total_paise"]:
                    best = {
                        "printed_total_paise": v.normalized_paise,
                        "printed_total_crore": round((v.normalized_paise or 0) / PAISE_PER_CRORE, 2),
                        "printed_total_text": sentence.strip()[:400],
                        "printed_total_source_chunk_id": chunk.get("chunk_id"),
                    }
    return best


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

    logger.info(f"Enriched output saved to: {output_path}")

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

    logger.info(f"Found {len(chunk_files)} report files to enrich")

    for i, chunk_file in enumerate(sorted(chunk_files), 1):
        logger.info(f"\n[{i}/{len(chunk_files)}] Processing: {chunk_file.name}")

        output_file = output_path / f"{chunk_file.stem}_enriched.json"

        try:
            result = enrich_report_file(str(chunk_file), str(output_file))
            results.append(result)
        except Exception as e:
            logger.error(f"  ERROR: {e}")
            continue

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("ENRICHMENT SUMMARY")
    logger.info("=" * 60)

    total_findings = sum(len(r.get("findings", [])) for r in results)
    total_recommendations = sum(len(r.get("recommendations", [])) for r in results)
    total_monetary = sum(
        r.get("statistics", {}).get("findings", {}).get("total_monetary_crore", 0)
        for r in results
    )

    logger.info(f"Reports processed: {len(results)}")
    logger.info(f"Total findings extracted: {total_findings}")
    logger.info(f"Total recommendations extracted: {total_recommendations}")
    logger.info(f"Total monetary value: ₹{total_monetary:,.2f} crore")

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
