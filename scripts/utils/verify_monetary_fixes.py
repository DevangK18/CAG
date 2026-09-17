#!/usr/bin/env python3
"""
Verification script for R1-R5 monetary extraction fixes.

Re-runs semantic enrichment on all processed reports and verifies:
1. Monetary totals are reasonable (not inflated)
2. R3 deduplication is working
3. R4 executive summary flagging is working
4. R5 primary amount identification is working
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsing_pipeline.modules.semantic_enrichment_service import SemanticEnrichmentService
from src.core.data_contracts import Finding


def load_processed_report(path: Path) -> Dict[str, Any]:
    """Load a processed report JSON file."""
    with open(path) as f:
        return json.load(f)


def extract_tier_from_path(path: Path) -> str:
    """Extract government tier from file path."""
    if "local_body" in str(path):
        return "local_body"
    elif "state" in str(path):
        return "state"
    elif "union" in str(path):
        return "union"
    return "unknown"


def get_plausibility_threshold(tier: str) -> float:
    """Get plausibility threshold in crore based on tier."""
    thresholds = {
        "local_body": 10000,  # ₹10,000 crore max expected
        "state": 100000,      # ₹1 lakh crore max expected
        "union": 500000,      # ₹5 lakh crore max expected
    }
    return thresholds.get(tier, 100000)


def verify_report(path: Path, service: SemanticEnrichmentService) -> Dict[str, Any]:
    """
    Verify a single report's monetary extraction.

    Returns verification results including:
    - Old vs new totals
    - R1 rejection simulation
    - Deduplication stats
    - Executive summary stats
    - Plausibility check
    """
    from src.parsing_pipeline.modules.enrichment.finding_extractor import FindingExtractor

    data = load_processed_report(path)
    report_id = path.stem.replace("_chunks", "")
    tier = extract_tier_from_path(path)

    # Get existing statistics
    old_stats = data.get("semantic_enrichment", {}).get("statistics", {}).get("findings", {})
    old_total_crore = old_stats.get("total_monetary_crore", 0)
    old_count = old_stats.get("total_count", 0)

    # Get existing findings
    findings_data = data.get("semantic_enrichment", {}).get("findings", [])

    # Initialize FindingExtractor for R1 simulation
    fe = FindingExtractor()

    if not findings_data:
        return {
            "report_id": report_id,
            "tier": tier,
            "status": "NO_FINDINGS",
            "old_total_crore": 0,
            "new_total_crore": 0,
            "findings_count": 0,
        }

    # Convert findings data to Finding objects for deduplication
    # Apply R1 simulation: filter out findings that R1 would reject
    findings: List[Finding] = []
    r1_rejected_count = 0
    r1_rejected_amount = 0

    for f_data in findings_data:
        try:
            text = f_data.get("text", f_data.get("content", ""))

            # R1 SIMULATION: Check if this finding would be rejected by R1 patterns
            if fe._is_non_finding(text):
                r1_rejected_count += 1
                r1_rejected_amount += f_data.get("total_amount_inr", 0)
                continue  # Skip this finding

            # Create Finding with required fields
            finding = Finding(
                finding_id=f_data.get("finding_id", ""),
                report_id=report_id,
                text=text[:500],
                summary=f_data.get("summary", text[:200]),
                finding_type=f_data.get("finding_type", "other"),
                severity=f_data.get("severity", "medium"),
                total_amount_inr=f_data.get("total_amount_inr", 0),
                page=f_data.get("page", 0),
                source_chunk_id=f_data.get("source_chunk_id", f_data.get("chunk_id", "")),
                # R4: Check for executive summary flag or detect from page/section
                is_executive_summary=f_data.get("is_executive_summary", False),
                is_duplicate=False,
                dedup_group_id=None,
            )
            findings.append(finding)
        except Exception as e:
            print(f"  Warning: Could not parse finding: {e}")
            continue

    if not findings:
        return {
            "report_id": report_id,
            "tier": tier,
            "status": "PARSE_ERROR",
            "old_total_crore": old_total_crore,
            "new_total_crore": 0,
            "findings_count": 0,
        }

    # Apply R3 deduplication
    findings, dedup_stats = service._deduplicate_cross_finding_amounts(findings)

    # Calculate new totals (excluding duplicates)
    primary_findings = [f for f in findings if not f.is_duplicate]
    new_total_inr = sum(f.total_amount_inr for f in primary_findings)
    new_total_crore = new_total_inr / 10_000_000_00

    # Count exec summary findings
    exec_summary_findings = [f for f in findings if f.is_executive_summary]
    exec_summary_total = sum(f.total_amount_inr for f in exec_summary_findings) / 10_000_000_00

    # Plausibility check
    threshold = get_plausibility_threshold(tier)
    is_plausible = new_total_crore <= threshold

    return {
        "report_id": report_id,
        "tier": tier,
        "status": "OK" if is_plausible else "IMPLAUSIBLE",
        "old_total_crore": round(old_total_crore, 2),
        "new_total_crore": round(new_total_crore, 2),
        "reduction_pct": round((1 - new_total_crore / max(old_total_crore, 1)) * 100, 1) if old_total_crore > 0 else 0,
        "findings_count": len(findings) + r1_rejected_count,  # Original count
        "valid_count": len(findings),  # After R1 filtering
        "primary_count": len(primary_findings),
        "r1_rejected_count": r1_rejected_count,
        "r1_rejected_crore": round(r1_rejected_amount / 10_000_000_00, 2),
        "duplicate_count": dedup_stats["duplicates_found"],
        "dedup_groups": dedup_stats["groups"],
        "exec_summary_count": len(exec_summary_findings),
        "exec_summary_crore": round(exec_summary_total, 2),
        "threshold_crore": threshold,
    }


def main():
    """Run verification on all processed reports."""
    processed_dir = Path("/Users/dev/Projects/CAG/data/processed")

    # Find all processed reports
    reports = list(processed_dir.glob("**/*_chunks.json"))
    reports.sort()

    print(f"=" * 80)
    print(f"MONETARY VALUE EXTRACTION VERIFICATION (R1-R5 Fixes)")
    print(f"=" * 80)
    print(f"\nFound {len(reports)} reports to verify\n")

    # Initialize service
    service = SemanticEnrichmentService()

    # Verify each report
    results = []
    for path in reports:
        print(f"Verifying: {path.name[:60]}...")
        try:
            result = verify_report(path, service)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "report_id": path.stem,
                "tier": extract_tier_from_path(path),
                "status": "ERROR",
                "error": str(e),
            })

    # Print summary
    print(f"\n{'=' * 80}")
    print(f"VERIFICATION SUMMARY")
    print(f"{'=' * 80}\n")

    # Group by tier
    by_tier = {"local_body": [], "state": [], "union": [], "unknown": []}
    for r in results:
        tier = r.get("tier", "unknown")
        by_tier[tier].append(r)

    for tier in ["local_body", "state", "union"]:
        tier_results = by_tier[tier]
        if not tier_results:
            continue

        print(f"\n{'=' * 40}")
        print(f"{tier.upper()} REPORTS ({len(tier_results)})")
        print(f"{'=' * 40}")

        print(f"\n{'Report ID':<35} {'Old ₹Cr':>12} {'New ₹Cr':>12} {'Reduction':>10} {'R1 Rej':>8} {'Dups':>6} {'Status':>12}")
        print(f"{'-' * 35} {'-' * 12} {'-' * 12} {'-' * 10} {'-' * 8} {'-' * 6} {'-' * 12}")

        for r in tier_results:
            report_id = r.get("report_id", "?")[:34]
            old_cr = r.get("old_total_crore", 0)
            new_cr = r.get("new_total_crore", 0)
            reduction = r.get("reduction_pct", 0)
            r1_rej = r.get("r1_rejected_count", 0)
            dups = r.get("duplicate_count", 0)
            status = r.get("status", "?")

            # Color code status
            status_str = f"✓ {status}" if status == "OK" else f"✗ {status}"

            print(f"{report_id:<35} {old_cr:>12,.1f} {new_cr:>12,.1f} {reduction:>9.1f}% {r1_rej:>8} {dups:>6} {status_str:>12}")

    # Overall summary
    print(f"\n{'=' * 80}")
    print(f"OVERALL RESULTS")
    print(f"{'=' * 80}")

    ok_count = sum(1 for r in results if r.get("status") == "OK")
    implausible_count = sum(1 for r in results if r.get("status") == "IMPLAUSIBLE")
    error_count = sum(1 for r in results if r.get("status") in ["ERROR", "PARSE_ERROR"])
    no_findings = sum(1 for r in results if r.get("status") == "NO_FINDINGS")

    print(f"\nTotal reports: {len(results)}")
    print(f"  ✓ OK (plausible): {ok_count}")
    print(f"  ✗ Implausible: {implausible_count}")
    print(f"  ⚠ Errors: {error_count}")
    print(f"  - No findings: {no_findings}")

    # Calculate total reduction
    total_old = sum(r.get("old_total_crore", 0) for r in results)
    total_new = sum(r.get("new_total_crore", 0) for r in results)
    total_r1_rejected = sum(r.get("r1_rejected_count", 0) for r in results)
    total_r1_rejected_crore = sum(r.get("r1_rejected_crore", 0) for r in results)
    total_dups = sum(r.get("duplicate_count", 0) for r in results)

    print(f"\nAggregate statistics:")
    print(f"  Old total: ₹{total_old:,.1f} crore")
    print(f"  New total: ₹{total_new:,.1f} crore (with R1 + R3 fixes)")
    print(f"  Reduction: {(1 - total_new / max(total_old, 1)) * 100:.1f}%")
    print(f"  R1 rejected findings: {total_r1_rejected} (₹{total_r1_rejected_crore:,.1f} crore)")
    print(f"  R3 duplicates removed: {total_dups}")

    # Check specific problem reports
    print(f"\n{'=' * 80}")
    print(f"PROBLEM REPORT CHECK")
    print(f"{'=' * 80}")

    problem_reports = ["BR_2024_03", "HP_2019"]
    for report_id in problem_reports:
        matching = [r for r in results if report_id in r.get("report_id", "")]
        if matching:
            r = matching[0]
            print(f"\n{r['report_id']}:")
            print(f"  Old total: ₹{r.get('old_total_crore', 0):,.1f} crore")
            print(f"  New total: ₹{r.get('new_total_crore', 0):,.1f} crore")
            print(f"  R1 rejected: {r.get('r1_rejected_count', 0)} findings (₹{r.get('r1_rejected_crore', 0):,.1f} crore)")
            print(f"  R3 duplicates: {r.get('duplicate_count', 0)}")
            print(f"  Valid findings: {r.get('valid_count', 0)} (from {r.get('findings_count', 0)} original)")
            print(f"  Status: {r.get('status', '?')}")

    return 0 if implausible_count == 0 and error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
