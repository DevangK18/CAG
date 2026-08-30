#!/usr/bin/env python3
"""
Evaluate LLM Validation for Semantic Enrichment

P3: A/B comparison script to measure the effectiveness of hybrid LLM validation.

This script:
1. Loads processed report JSON files
2. Identifies low-confidence extractions (findings, sections)
3. Runs LLM validation on a sample
4. Compares results to measure precision lift
5. Calculates cost per report

Usage:
    # Dry run (no LLM calls, estimate costs only)
    python scripts/evaluate_llm_validation.py --dry-run

    # Validate 5 reports
    python scripts/evaluate_llm_validation.py --reports 5

    # Validate specific reports
    python scripts/evaluate_llm_validation.py --input data/processed/union/2025_04_chunks.json

    # Full evaluation with cost tracking
    python scripts/evaluate_llm_validation.py --reports 10 --output results/llm_validation_eval.json
"""

import argparse
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Optional, Any
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsing_pipeline.modules.enrichment.llm_validator import (
    LLMValidator,
    ValidationRequest,
    ValidationVerdict,
    create_finding_validation_request,
    create_section_validation_request,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class EvaluationMetrics:
    """Metrics from LLM validation evaluation."""
    report_id: str
    total_findings: int
    low_confidence_findings: int
    findings_validated: int
    findings_valid: int
    findings_invalid: int
    findings_uncertain: int

    total_sections: int
    low_confidence_sections: int
    sections_validated: int
    sections_valid: int
    sections_invalid: int
    sections_uncertain: int

    estimated_cost_usd: float
    actual_cost_usd: float


@dataclass
class AggregateMetrics:
    """Aggregate metrics across all reports."""
    total_reports: int
    total_findings: int
    total_low_confidence_findings: int
    findings_precision_before: float  # Assuming all low-conf are correct
    findings_precision_after: float   # After LLM validation
    invalid_findings_caught: int

    total_sections: int
    total_low_confidence_sections: int
    sections_precision_before: float
    sections_precision_after: float
    invalid_sections_caught: int

    total_cost_usd: float
    cost_per_report_usd: float


def load_report(path: Path) -> Optional[Dict]:
    """Load a processed report JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
        return None


def extract_low_confidence_items(
    report_data: Dict,
    confidence_lower: float = 0.4,
    confidence_upper: float = 0.7,
) -> tuple[List[Dict], List[Dict]]:
    """
    Extract low-confidence findings and sections from report.

    Returns:
        Tuple of (low_confidence_findings, low_confidence_sections)
    """
    low_conf_findings = []
    low_conf_sections = []

    # Extract findings from semantic_enrichment
    enrichment = report_data.get("semantic_enrichment", {})
    findings = enrichment.get("findings", [])

    for finding in findings:
        confidence = finding.get("confidence", 0.5)
        if confidence_lower <= confidence < confidence_upper:
            # Find the source chunk text
            chunk_id = finding.get("source_chunk_id", "")
            chunk_text = ""
            for chunk in report_data.get("child_chunks", []):
                if chunk.get("chunk_id") == chunk_id:
                    chunk_text = chunk.get("content", "")
                    break

            low_conf_findings.append({
                "finding": finding,
                "chunk_text": chunk_text,
                "confidence": confidence,
            })

    # Extract low-confidence sections
    sections = enrichment.get("section_classifications", [])
    for section in sections:
        # Check is_low_confidence flag (P1-C) or confidence range
        is_low_conf = section.get("is_low_confidence", False)
        confidence = section.get("confidence", 0.5)

        if is_low_conf or (confidence_lower <= confidence < confidence_upper):
            low_conf_sections.append({
                "classification": section,
                "section_title": section.get("section_title", ""),
                "confidence": confidence,
            })

    return low_conf_findings, low_conf_sections


def evaluate_report(
    report_data: Dict,
    validator: LLMValidator,
    dry_run: bool = False,
) -> EvaluationMetrics:
    """
    Evaluate LLM validation on a single report.

    Args:
        report_data: Loaded report JSON
        validator: LLMValidator instance
        dry_run: If True, don't make actual LLM calls

    Returns:
        EvaluationMetrics for this report
    """
    report_id = report_data.get("report_metadata", {}).get("report_id", "unknown")
    logger.info(f"Evaluating report: {report_id}")

    # Get all findings and sections
    enrichment = report_data.get("semantic_enrichment", {})
    all_findings = enrichment.get("findings", [])
    all_sections = enrichment.get("section_classifications", [])

    # Extract low-confidence items
    low_conf_findings, low_conf_sections = extract_low_confidence_items(report_data)

    # Initialize metrics
    metrics = EvaluationMetrics(
        report_id=report_id,
        total_findings=len(all_findings),
        low_confidence_findings=len(low_conf_findings),
        findings_validated=0,
        findings_valid=0,
        findings_invalid=0,
        findings_uncertain=0,
        total_sections=len(all_sections),
        low_confidence_sections=len(low_conf_sections),
        sections_validated=0,
        sections_valid=0,
        sections_invalid=0,
        sections_uncertain=0,
        estimated_cost_usd=0.0,
        actual_cost_usd=0.0,
    )

    # Estimate cost (without making calls)
    # GPT-4o Mini: ~850 tokens input, ~60 tokens output per validation
    # $0.15/1M input, $0.60/1M output
    total_validations = len(low_conf_findings) + len(low_conf_sections)
    input_tokens = total_validations * 850
    output_tokens = total_validations * 60
    estimated_cost = (input_tokens * 0.15 / 1_000_000) + (output_tokens * 0.60 / 1_000_000)
    metrics.estimated_cost_usd = estimated_cost

    if dry_run:
        logger.info(
            f"  [DRY RUN] Would validate {len(low_conf_findings)} findings, "
            f"{len(low_conf_sections)} sections. Estimated cost: ${estimated_cost:.4f}"
        )
        return metrics

    # Validate findings (using validate_and_collect for data collection)
    for item in low_conf_findings:
        request = create_finding_validation_request(
            finding=item["finding"],
            chunk_text=item["chunk_text"],
        )
        # Use validate_and_collect to save refinement data
        result = validator.validate_and_collect(request, report_id=report_id)
        metrics.findings_validated += 1

        if result.verdict == ValidationVerdict.VALID:
            metrics.findings_valid += 1
        elif result.verdict == ValidationVerdict.INVALID:
            metrics.findings_invalid += 1
            logger.info(f"  Invalid finding detected: {result.reasoning}")
        else:
            metrics.findings_uncertain += 1

    # Validate sections (using validate_and_collect for data collection)
    for item in low_conf_sections:
        request = create_section_validation_request(
            classification=item["classification"],
            section_title=item["section_title"],
        )
        # Use validate_and_collect to save refinement data
        result = validator.validate_and_collect(request, report_id=report_id)
        metrics.sections_validated += 1

        if result.verdict == ValidationVerdict.VALID:
            metrics.sections_valid += 1
        elif result.verdict == ValidationVerdict.INVALID:
            metrics.sections_invalid += 1
            logger.info(f"  Invalid section detected: {result.reasoning}")
        else:
            metrics.sections_uncertain += 1

    # Calculate actual cost
    actual_input_tokens = metrics.findings_validated * 850 + metrics.sections_validated * 850
    actual_output_tokens = metrics.findings_validated * 60 + metrics.sections_validated * 60
    metrics.actual_cost_usd = (
        (actual_input_tokens * 0.15 / 1_000_000) +
        (actual_output_tokens * 0.60 / 1_000_000)
    )

    logger.info(
        f"  Findings: {metrics.findings_valid} valid, {metrics.findings_invalid} invalid, "
        f"{metrics.findings_uncertain} uncertain"
    )
    logger.info(
        f"  Sections: {metrics.sections_valid} valid, {metrics.sections_invalid} invalid, "
        f"{metrics.sections_uncertain} uncertain"
    )
    logger.info(f"  Cost: ${metrics.actual_cost_usd:.4f}")

    return metrics


def aggregate_metrics(report_metrics: List[EvaluationMetrics]) -> AggregateMetrics:
    """Aggregate metrics across all evaluated reports."""
    if not report_metrics:
        return AggregateMetrics(
            total_reports=0,
            total_findings=0,
            total_low_confidence_findings=0,
            findings_precision_before=0.0,
            findings_precision_after=0.0,
            invalid_findings_caught=0,
            total_sections=0,
            total_low_confidence_sections=0,
            sections_precision_before=0.0,
            sections_precision_after=0.0,
            invalid_sections_caught=0,
            total_cost_usd=0.0,
            cost_per_report_usd=0.0,
        )

    total_findings = sum(m.total_findings for m in report_metrics)
    total_low_conf_findings = sum(m.low_confidence_findings for m in report_metrics)
    total_invalid_findings = sum(m.findings_invalid for m in report_metrics)
    total_validated_findings = sum(m.findings_validated for m in report_metrics)

    total_sections = sum(m.total_sections for m in report_metrics)
    total_low_conf_sections = sum(m.low_confidence_sections for m in report_metrics)
    total_invalid_sections = sum(m.sections_invalid for m in report_metrics)
    total_validated_sections = sum(m.sections_validated for m in report_metrics)

    total_cost = sum(m.actual_cost_usd for m in report_metrics)

    # Calculate precision improvement
    # Before: Assume all extractions are correct (100% precision on accepted)
    # After: Remove invalid extractions caught by LLM

    # For findings in validation band:
    # Before precision: (low_conf - invalid) / low_conf (we don't know invalids yet)
    # After precision: (validated - invalid) / validated

    findings_precision_before = 1.0  # Assuming we accept all
    if total_validated_findings > 0:
        findings_precision_after = (
            (total_validated_findings - total_invalid_findings) / total_validated_findings
        )
    else:
        findings_precision_after = 1.0

    sections_precision_before = 1.0
    if total_validated_sections > 0:
        sections_precision_after = (
            (total_validated_sections - total_invalid_sections) / total_validated_sections
        )
    else:
        sections_precision_after = 1.0

    return AggregateMetrics(
        total_reports=len(report_metrics),
        total_findings=total_findings,
        total_low_confidence_findings=total_low_conf_findings,
        findings_precision_before=findings_precision_before,
        findings_precision_after=findings_precision_after,
        invalid_findings_caught=total_invalid_findings,
        total_sections=total_sections,
        total_low_confidence_sections=total_low_conf_sections,
        sections_precision_before=sections_precision_before,
        sections_precision_after=sections_precision_after,
        invalid_sections_caught=total_invalid_sections,
        total_cost_usd=total_cost,
        cost_per_report_usd=total_cost / len(report_metrics) if report_metrics else 0.0,
    )


def find_processed_reports(
    data_dir: Path = Path("data/processed"),
    limit: Optional[int] = None,
) -> List[Path]:
    """Find all processed report JSON files."""
    reports = []

    for tier_dir in ["union", "state", "local_body"]:
        tier_path = data_dir / tier_dir
        if tier_path.exists():
            for json_file in tier_path.glob("*_chunks.json"):
                reports.append(json_file)

    # Sort by modification time (newest first)
    reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if limit:
        reports = reports[:limit]

    return reports


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate LLM validation for semantic enrichment"
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        nargs="*",
        help="Specific report JSON files to evaluate"
    )
    parser.add_argument(
        "--reports", "-n",
        type=int,
        default=5,
        help="Number of reports to evaluate (default: 5)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate costs without making LLM calls"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output file for detailed results (JSON)"
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model for validation (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--confidence-lower",
        type=float,
        default=0.4,
        help="Lower confidence bound for validation (default: 0.4)"
    )
    parser.add_argument(
        "--confidence-upper",
        type=float,
        default=0.7,
        help="Upper confidence bound for validation (default: 0.7)"
    )

    args = parser.parse_args()

    # Find reports to evaluate
    if args.input:
        report_paths = [p for p in args.input if p.exists()]
    else:
        report_paths = find_processed_reports(limit=args.reports)

    if not report_paths:
        logger.error("No reports found to evaluate")
        sys.exit(1)

    logger.info(f"Found {len(report_paths)} reports to evaluate")

    # Initialize validator
    validator = LLMValidator(
        model=args.model,
        confidence_lower_bound=args.confidence_lower,
        confidence_upper_bound=args.confidence_upper,
    )

    # Evaluate each report
    all_metrics = []
    for report_path in report_paths:
        report_data = load_report(report_path)
        if report_data:
            metrics = evaluate_report(report_data, validator, dry_run=args.dry_run)
            all_metrics.append(metrics)

    # Aggregate results
    aggregate = aggregate_metrics(all_metrics)

    # Print summary
    print("\n" + "=" * 70)
    print("LLM VALIDATION EVALUATION SUMMARY")
    print("=" * 70)
    print(f"\nReports evaluated: {aggregate.total_reports}")
    print(f"\nFINDINGS:")
    print(f"  Total findings: {aggregate.total_findings}")
    print(f"  Low-confidence findings: {aggregate.total_low_confidence_findings}")
    print(f"  Invalid findings caught: {aggregate.invalid_findings_caught}")
    if aggregate.total_low_confidence_findings > 0:
        invalid_rate = aggregate.invalid_findings_caught / aggregate.total_low_confidence_findings * 100
        print(f"  Invalid rate in low-conf band: {invalid_rate:.1f}%")
    print(f"  Precision lift: {aggregate.findings_precision_before:.1%} -> {aggregate.findings_precision_after:.1%}")

    print(f"\nSECTIONS:")
    print(f"  Total sections: {aggregate.total_sections}")
    print(f"  Low-confidence sections: {aggregate.total_low_confidence_sections}")
    print(f"  Invalid sections caught: {aggregate.invalid_sections_caught}")
    if aggregate.total_low_confidence_sections > 0:
        invalid_rate = aggregate.invalid_sections_caught / aggregate.total_low_confidence_sections * 100
        print(f"  Invalid rate in low-conf band: {invalid_rate:.1f}%")
    print(f"  Precision lift: {aggregate.sections_precision_before:.1%} -> {aggregate.sections_precision_after:.1%}")

    print(f"\nCOST:")
    print(f"  Total cost: ${aggregate.total_cost_usd:.4f}")
    print(f"  Cost per report: ${aggregate.cost_per_report_usd:.4f}")
    if aggregate.invalid_findings_caught + aggregate.invalid_sections_caught > 0:
        cost_per_error = aggregate.total_cost_usd / (
            aggregate.invalid_findings_caught + aggregate.invalid_sections_caught
        )
        print(f"  Cost per error caught: ${cost_per_error:.4f}")

    # Save detailed results
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        results = {
            "aggregate": asdict(aggregate),
            "per_report": [asdict(m) for m in all_metrics],
            "config": {
                "model": args.model,
                "confidence_lower": args.confidence_lower,
                "confidence_upper": args.confidence_upper,
                "dry_run": args.dry_run,
            }
        }
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"\nDetailed results saved to: {args.output}")


if __name__ == "__main__":
    main()
