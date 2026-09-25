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
from typing import TYPE_CHECKING, List, Dict, Optional, Any

if TYPE_CHECKING:
    from src.parsing_pipeline.instrumentation import TraceEmitter

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

# LLM Validator for hybrid validation (P3)
from src.parsing_pipeline.modules.enrichment.llm_validator import (
    LLMValidator,
    ValidationVerdict,
    create_finding_validation_request,
)
from src.parsing_pipeline.modules.enrichment.pattern_loader import get_pattern_loader


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

        # P3: LLM Validator for hybrid validation
        self._llm_validator: Optional[LLMValidator] = None
        self._llm_validation_enabled = False
        try:
            llm_config = get_pattern_loader().get_llm_validation_config()
            self._llm_validation_enabled = llm_config.get("enabled", False)
            if self._llm_validation_enabled:
                self._llm_validator = LLMValidator()
                logger.info("LLM validation enabled for low-confidence findings")
        except Exception as e:
            logger.debug(f"LLM validation not configured: {e}")

        # Current report type (set per document)
        self._current_report_type = "general"

        logger.info(
            "SemanticEnrichmentService initialized with focused extractors, "
            "evidence linking, temporal extraction, annexure linking, "
            f"cross-reference resolution, llm_validation={self._llm_validation_enabled}."
        )

    def enrich_document(
        self,
        report_id: str,
        report_metadata: Dict,
        parent_chunks: List[Dict],
        child_chunks: List[Dict],
        task: Optional[DocumentTask] = None,
        trace_emitter: Optional["TraceEmitter"] = None,
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

        # 2. Extract findings (report-type aware with tier-specific severity)
        government_body_type = report_metadata.get("government_body_type", "union")
        try:
            self._finding_extractor.set_report_type(self._current_report_type)
            # P1-13: Pass parent_chunks for source attribution (section from toc_entry)
            findings = self._finding_extractor.extract_findings(
                report_id, child_chunks, government_body_type, parent_chunks
            )

            # Populate entities_mentioned for each finding
            for finding in findings:
                try:
                    finding.entities_mentioned = self._entity_extractor.extract_entities_from_text(
                        finding.text
                    )
                except Exception as entity_err:
                    logger.warning(f"  Entity extraction for finding failed: {entity_err}")
                    finding.entities_mentioned = []

            logger.info(f"  Extracted {len(findings)} findings")

            # P3: LLM validation for low-confidence findings
            if self._llm_validation_enabled and self._llm_validator and findings:
                findings = self._validate_findings_with_llm(
                    findings, child_chunks, report_id, trace_emitter
                )

        except Exception as e:
            logger.warning(f"  Finding extraction failed: {e}")
            findings = []
            trace_emitter.emit_red_flag(
                "9", "finding_extractor_failed",
                {"error": str(e), "report_id": report_id}
            )

        # 3. Extract recommendations with multi-strategy extractor (with error handling - P1-A)
        try:
            raw_recs = self._rec_extractor.extract_all(
                report_id,
                parent_chunks,
                child_chunks,
                [s.model_dump() for s in section_classifications],
            )

            # Convert to Recommendation data contracts
            recommendations = []
            for i, raw in enumerate(raw_recs):
                recommendations.append(
                    Recommendation(
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
                        extraction_strategy=raw.extraction_strategy,
                        rec_number=raw.rec_number,
                        paragraph_citations=raw.paragraph_citations,
                    )
                )

            # Print extraction strategy breakdown
            structural_count = sum(
                1 for r in raw_recs if r.extraction_strategy == "structural"
            )
            numbered_count = sum(
                1 for r in raw_recs if r.extraction_strategy == "numbered"
            )
            verb_count = sum(1 for r in raw_recs if r.extraction_strategy == "verb")
            logger.info(
                f"  Extracted {len(recommendations)} recommendations "
                f"(structural={structural_count}, numbered={numbered_count}, verb={verb_count})"
            )
        except Exception as e:
            logger.warning(f"  Recommendation extraction failed: {e}")
            recommendations = []
            raw_recs = []
            trace_emitter.emit_red_flag(
                "9", "recommendation_extractor_failed",
                {"error": str(e), "report_id": report_id}
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
            report_metadata, findings, recommendations, section_classifications
        )

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
            total_monetary_crore = statistics.get("findings", {}).get("total_monetary_crore", 0)
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
                    "monetary_crore": statistics.get("findings", {}).get("total_monetary_crore", 0),
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

    def _validate_findings_with_llm(
        self,
        findings: List[Finding],
        child_chunks: List[Dict],
        report_id: str,
        trace_emitter: "TraceEmitter",
    ) -> List[Finding]:
        """
        P3: Validate low-confidence findings using LLM.

        Filters out findings that the LLM determines are invalid (false positives).
        Collects data on invalid findings for pattern refinement.

        Args:
            findings: List of extracted findings
            child_chunks: Child chunks for text lookup
            report_id: Report ID for tracking
            trace_emitter: Trace emitter for instrumentation

        Returns:
            Filtered list of findings (invalid ones removed)
        """
        if not self._llm_validator:
            return findings

        # Build chunk lookup for text retrieval
        chunk_lookup = {c.get("chunk_id"): c.get("content", "") for c in child_chunks}

        # Identify findings needing validation
        to_validate = []
        for finding in findings:
            confidence = getattr(finding, "confidence", 0.5)
            if self._llm_validator.needs_validation(confidence):
                to_validate.append(finding)

        if not to_validate:
            logger.info("  No findings need LLM validation")
            return findings

        logger.info(f"  Validating {len(to_validate)} low-confidence findings via LLM...")

        # Validate each finding
        validated_findings = []
        invalid_count = 0
        valid_count = 0

        for finding in findings:
            confidence = getattr(finding, "confidence", 0.5)

            if not self._llm_validator.needs_validation(confidence):
                # High confidence or below threshold - keep as-is
                validated_findings.append(finding)
                continue

            # Get chunk text
            chunk_text = chunk_lookup.get(finding.source_chunk_id, finding.text)

            # Create validation request
            request = create_finding_validation_request(
                finding=finding.model_dump(),
                chunk_text=chunk_text,
                parent_section=finding.chapter,
            )

            # Validate with data collection
            try:
                result = self._llm_validator.validate_and_collect(
                    request, report_id=report_id
                )

                if result.verdict == ValidationVerdict.INVALID:
                    invalid_count += 1
                    logger.debug(f"    Invalid finding filtered: {finding.finding_id} - {result.reasoning[:100]}")
                    # Don't add to validated_findings - this filters it out
                else:
                    valid_count += 1
                    validated_findings.append(finding)

            except Exception as e:
                logger.warning(f"    LLM validation error for {finding.finding_id}: {e}")
                # On error, keep the finding (fail-open)
                validated_findings.append(finding)

        # Emit trace data
        trace_emitter.emit_io(
            "9",
            {"llm_validation_input": len(to_validate)},
            {
                "llm_validated": len(to_validate),
                "llm_valid": valid_count,
                "llm_invalid": invalid_count,
                "findings_after_validation": len(validated_findings),
            },
        )

        if invalid_count > 0:
            logger.info(
                f"  LLM validation: {invalid_count} invalid findings filtered, "
                f"{valid_count} validated, {len(validated_findings)} total remaining"
            )

        return validated_findings

    def _link_findings_to_recommendations(
        self,
        findings: List[Finding],
        recommendations: List[Recommendation],
    ) -> None:
        """Link related findings and recommendations based on proximity and content."""
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

    def _deduplicate_cross_finding_amounts(
        self, findings: List[Finding], tolerance: float = 0.01, page_gap: int = 15
    ) -> tuple[List[Finding], Dict[str, Any]]:
        """
        R3: Deduplicate monetary amounts appearing in multiple findings.

        When the same audit finding amount appears multiple times (e.g., in
        executive summary and detailed chapter), marks later occurrences as
        duplicates to avoid inflating totals.

        Strategy:
        - Group by similar amounts (within tolerance)
        - Check page proximity (within page_gap pages)
        - Mark later occurrences (by page number) as duplicates
        - First occurrence keeps is_duplicate=False

        Args:
            findings: List of Finding objects
            tolerance: Tolerance for amount matching (default 1%)
            page_gap: Maximum page distance to consider as duplicate (default 15)

        Returns:
            Tuple of (modified findings list, dedup statistics dict)
        """
        from collections import defaultdict

        if not findings:
            return findings, {"groups": 0, "duplicates_found": 0, "total_examined": 0}

        # Build list of (amount, page, finding) for comparison
        findings_with_amounts: List[tuple[int, int, Finding]] = []

        for f in findings:
            # Use total_amount_inr for comparison
            if hasattr(f, 'total_amount_inr') and f.total_amount_inr and f.total_amount_inr > 0:
                finding_page = f.page if hasattr(f, 'page') and f.page else 0
                findings_with_amounts.append((f.total_amount_inr, finding_page, f))

        # Group by similar amounts using pairwise comparison
        # Two amounts are "similar" if they're within tolerance of each other
        processed: set[str] = set()  # Track which findings have been processed

        dedup_stats = {
            "groups": 0,
            "duplicates_found": 0,
            "total_examined": len(findings),
        }

        # Sort by page to ensure first occurrence is earliest
        findings_with_amounts.sort(key=lambda x: x[1])

        for i, (amount_i, page_i, finding_i) in enumerate(findings_with_amounts):
            if finding_i.finding_id in processed:
                continue

            # Find all other findings with similar amounts
            similar_group = [(amount_i, page_i, finding_i)]
            processed.add(finding_i.finding_id)

            for j, (amount_j, page_j, finding_j) in enumerate(findings_with_amounts):
                if i == j or finding_j.finding_id in processed:
                    continue

                # Check if amounts are within tolerance
                max_amount = max(amount_i, amount_j)
                min_amount = min(amount_i, amount_j)
                if max_amount > 0 and (max_amount - min_amount) / max_amount <= tolerance:
                    similar_group.append((amount_j, page_j, finding_j))
                    processed.add(finding_j.finding_id)

            # If we have multiple similar findings, mark duplicates
            if len(similar_group) > 1:
                # First (by page) is original, rest are duplicates if within page_gap
                # Sort is already done, so first item is earliest
                first_page = similar_group[0][1]
                group_id = f"dedup_{amount_i}_{i}"

                for k in range(1, len(similar_group)):
                    _, current_page, current_finding = similar_group[k]

                    # If within page_gap of first occurrence, mark as duplicate
                    if current_page - first_page <= page_gap:
                        current_finding.is_duplicate = True
                        current_finding.dedup_group_id = group_id
                        dedup_stats["duplicates_found"] += 1

                # Count as a group if we marked any duplicates in this group
                group_has_dups = any(
                    similar_group[k][2].is_duplicate for k in range(1, len(similar_group))
                )
                if group_has_dups:
                    dedup_stats["groups"] += 1

        logger.info(
            f"  R3 Dedup: {dedup_stats['duplicates_found']} duplicates found in "
            f"{dedup_stats['groups']} groups (examined {dedup_stats['total_examined']} findings)"
        )

        return findings, dedup_stats

    def _calculate_statistics(
        self,
        report_metadata: Dict,
        findings: List[Finding],
        recommendations: List[Recommendation],
        sections: List[SectionClassification],
    ) -> Dict[str, Any]:
        """Calculate aggregate statistics for the report."""
        # R3: Deduplicate findings before calculating totals
        findings, dedup_stats = self._deduplicate_cross_finding_amounts(findings)

        # R3 + R4: Filter out duplicates and exec summary for primary totals
        primary_findings = [
            f for f in findings
            if not getattr(f, 'is_duplicate', False)
            and not getattr(f, 'is_executive_summary', False)
        ]

        # Headline total: largest amount per primary finding, each distinct amount counted once.
        # Summing every amount in a finding double-counts outlays, budgets and repeated figures.
        seen_amounts: set = set()
        total_monetary = 0
        for f in primary_findings:
            amount = f.monetary_value or 0
            if amount and amount not in seen_amounts:
                seen_amounts.add(amount)
                total_monetary += amount
        total_monetary_crore = total_monetary / 10_000_000_00

        # Also track raw totals for transparency
        raw_total_monetary = sum(f.total_amount_inr for f in findings)
        raw_total_monetary_crore = raw_total_monetary / 10_000_000_00

        # R4: Track executive summary totals separately
        exec_summary_findings = [
            f for f in findings if getattr(f, 'is_executive_summary', False)
        ]
        exec_summary_total = sum(f.total_amount_inr for f in exec_summary_findings)
        exec_summary_total_crore = exec_summary_total / 10_000_000_00

        # R3: Track duplicate totals
        duplicate_findings = [
            f for f in findings if getattr(f, 'is_duplicate', False)
        ]
        duplicate_total = sum(f.total_amount_inr for f in duplicate_findings)

        # Finding statistics by type (using primary findings only)
        findings_by_type: Dict[str, Dict] = {}
        for f in primary_findings:
            ft = f.finding_type
            if ft not in findings_by_type:
                findings_by_type[ft] = {"count": 0, "total_inr": 0}
            findings_by_type[ft]["count"] += 1
            findings_by_type[ft]["total_inr"] += f.monetary_value or 0

        # Convert to crore for readability
        for ft in findings_by_type:
            findings_by_type[ft]["total_crore"] = (
                findings_by_type[ft]["total_inr"] / 10_000_000_00
            )

        # Severity distribution
        severity_counts: Dict[str, int] = {}
        for f in findings:
            sev = f.severity
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Section type distribution
        section_type_counts: Dict[str, int] = {}
        for s in sections:
            st = s.section_type
            section_type_counts[st] = section_type_counts.get(st, 0) + 1

        # Recommendation statistics
        target_entity_counts: Dict[str, int] = {}
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
                "detected_report_type": self._current_report_type,
                "publication_date": report_metadata.get("publication_date", "Unknown"),
            },
            "findings": {
                "total_count": len(findings),
                "primary_count": len(primary_findings),  # R3+R4: Non-duplicate, non-exec-summary
                "total_monetary_inr": total_monetary,  # Distinct max amount per primary finding
                "total_monetary_crore": round(total_monetary_crore, 2),
                "raw_total_monetary_inr": raw_total_monetary,  # R3: Before dedup
                "raw_total_monetary_crore": round(raw_total_monetary_crore, 2),
                "by_type": findings_by_type,
                "by_severity": severity_counts,
                # R3: Deduplication stats
                "dedup_stats": dedup_stats,
                "duplicate_count": len(duplicate_findings),
                "duplicate_total_inr": duplicate_total,
                # R4: Executive summary breakdown
                "exec_summary_count": len(exec_summary_findings),
                "exec_summary_total_inr": exec_summary_total,
                "exec_summary_total_crore": round(exec_summary_total_crore, 2),
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
