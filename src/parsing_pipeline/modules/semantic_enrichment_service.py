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

        logger.info(
            "SemanticEnrichmentService initialized with focused extractors, "
            "evidence linking, temporal extraction, annexure linking, "
            "and cross-reference resolution."
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

        # 1. Classify sections
        section_classifications = self._section_classifier.classify_sections(
            parent_chunks
        )
        logger.info(f"  Classified {len(section_classifications)} sections")

        # 2. Extract findings (report-type aware with tier-specific severity)
        government_body_type = report_metadata.get("government_body_type", "union")
        self._finding_extractor.set_report_type(self._current_report_type)
        findings = self._finding_extractor.extract_findings(
            report_id, child_chunks, government_body_type
        )

        # Populate entities_mentioned for each finding
        for finding in findings:
            finding.entities_mentioned = self._entity_extractor.extract_entities_from_text(
                finding.text
            )

        logger.info(f"  Extracted {len(findings)} findings")

        # 3. Extract recommendations with multi-strategy extractor
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

        # 4. Link findings to recommendations
        self._link_findings_to_recommendations(findings, recommendations)

        # 5. Create evidence links for findings
        evidence_links_map = self._link_evidence_to_findings(findings, child_chunks)
        logger.info(f"  Created evidence links for {len(evidence_links_map)} findings")

        # 5b. Link findings to annexures
        annexure_links = self._annexure_linker.link_annexures(
            child_chunks,
            parent_chunks,
            [f.model_dump() for f in findings],
        )
        resolved = sum(1 for link in annexure_links if link["resolved"])
        logger.info(f"  Annexure links: {len(annexure_links)} references, {resolved} resolved")

        # 6. Extract entities
        entities = self._entity_extractor.extract_entities(child_chunks)
        logger.info(
            f"  Extracted entities: {', '.join(f'{k}={len(v)}' for k, v in entities.items())}"
        )

        # 6b. Detect box elements
        box_elements = self._box_extractor.detect_box_elements(child_chunks)
        if box_elements:
            logger.info(f"  Detected {len(box_elements)} box elements")

        # 6c. Parse executive summary
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

        # 7. Extract temporal metadata
        temporal_coverage = self._temporal_extractor.extract_temporal_metadata(
            child_chunks, [s.model_dump() for s in section_classifications]
        )
        logger.info(
            f"  Temporal: audit_period={temporal_coverage.get('audit_period')}, "
            f"ref_years={len(temporal_coverage.get('reference_years', []))}"
        )

        # Annotate findings with temporal context
        for finding in findings:
            finding.reference_years = self._temporal_extractor.extract_reference_years(
                finding.text
            )
            if temporal_coverage.get("audit_period"):
                finding.audit_period = temporal_coverage["audit_period"]

        # 8. Resolve cross-chunk references
        cross_references = self._xref_resolver.resolve_references(
            child_chunks, parent_chunks
        )
        resolved_xrefs = sum(1 for x in cross_references if x["resolved"])
        logger.info(
            f"  Cross-references: {len(cross_references)} found, {resolved_xrefs} resolved"
        )

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
            if findings and other_count / len(findings) > 0.30:
                trace_emitter.emit_red_flag(
                    "9",
                    "High 'other' finding ratio",
                    {
                        "other_count": other_count,
                        "total_findings": len(findings),
                        "percentage": round(other_count / len(findings) * 100, 1),
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
        findings_by_type: Dict[str, Dict] = {}
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
