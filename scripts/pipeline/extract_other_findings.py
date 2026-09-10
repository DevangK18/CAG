"""
Extract "Other" Findings Analysis

Extracts all findings classified as "other" from State and Local Body reports
for manual review and potential reclassification.

Usage:
    poetry run python scripts/extract_other_findings.py

Output:
    logs/other_findings_analysis.md
"""

import json
import re
from pathlib import Path
from collections import Counter
from datetime import datetime


def load_chunks_file(file_path: Path) -> dict:
    """Load a *_chunks.json file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_chunk_content(child_chunks: list, chunk_id: str) -> str:
    """Look up chunk content by ID."""
    for chunk in child_chunks:
        if chunk.get("chunk_id") == chunk_id:
            return chunk.get("content", "")
    return ""


def get_hierarchy_string(finding: dict) -> str:
    """Extract hierarchy/section info from finding."""
    # Try different fields that might contain section info
    if finding.get("chapter"):
        return finding["chapter"]
    if finding.get("section"):
        return finding["section"]
    if finding.get("hierarchy"):
        h = finding["hierarchy"]
        if isinstance(h, dict):
            # Get deepest level
            return h.get("level_3") or h.get("level_2") or h.get("level_1") or str(h)
        return str(h)
    return "Unknown"


def extract_monetary_value(finding: dict) -> str:
    """Extract monetary value from finding."""
    amount = finding.get("total_amount_inr", 0)
    if amount and amount > 0:
        # Format in lakhs/crores for readability
        if amount >= 10000000:  # 1 crore
            return f"₹{amount / 10000000:.2f} Cr"
        elif amount >= 100000:  # 1 lakh
            return f"₹{amount / 100000:.2f} L"
        else:
            return f"₹{amount:,.0f}"
    return "none"


def extract_ngrams(text: str, n: int = 2) -> list:
    """Extract n-grams from text for frequency analysis."""
    # Clean and tokenize
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    # Filter common stopwords
    stopwords = {
        'the', 'and', 'for', 'that', 'with', 'was', 'were', 'are', 'been',
        'have', 'has', 'had', 'this', 'from', 'which', 'not', 'but', 'also',
        'its', 'their', 'they', 'would', 'could', 'should', 'may', 'can',
        'will', 'shall', 'being', 'such', 'any', 'all', 'per', 'cent',
        'during', 'period', 'year', 'years', 'audit', 'observed', 'noticed',
        'found', 'however', 'therefore', 'thus', 'hence', 'further', 'regard',
        'respect', 'case', 'cases', 'report', 'department', 'government',
        'state', 'amount', 'total', 'lakh', 'crore', 'rupees', 'inr'
    }
    filtered = [w for w in words if w not in stopwords]

    # Generate n-grams
    ngrams = []
    for i in range(len(filtered) - n + 1):
        ngram = ' '.join(filtered[i:i + n])
        ngrams.append(ngram)
    return ngrams


def process_reports(data_dirs: list) -> tuple:
    """
    Process all reports and extract "other" findings.

    Returns:
        (findings_by_report, all_texts) - findings grouped by report and all finding texts
    """
    findings_by_report = {}
    all_texts = []

    for data_dir in data_dirs:
        data_path = Path(data_dir)
        if not data_path.exists():
            print(f"⚠️  Directory not found: {data_dir}")
            continue

        json_files = sorted(data_path.glob("*_chunks.json"))
        print(f"📂 Found {len(json_files)} files in {data_dir}")

        for json_file in json_files:
            try:
                data = load_chunks_file(json_file)
                report_id = data.get("report_metadata", {}).get("report_id", json_file.stem.replace("_chunks", ""))

                # Get findings
                enrichment = data.get("semantic_enrichment", {})
                findings = enrichment.get("findings", [])
                child_chunks = data.get("child_chunks", [])

                # Filter for "other" findings
                other_findings = [f for f in findings if f.get("finding_type") == "other"]

                if not other_findings:
                    continue

                report_findings = []
                for finding in other_findings:
                    # Get source chunk content
                    source_chunk_id = finding.get("source_chunk_id", "")
                    chunk_content = get_chunk_content(child_chunks, source_chunk_id)

                    finding_data = {
                        "report_id": report_id,
                        "section": get_hierarchy_string(finding),
                        "severity": finding.get("severity", "unknown"),
                        "monetary": extract_monetary_value(finding),
                        "source_chunk_id": source_chunk_id,
                        "chunk_content": chunk_content,
                        "description": finding.get("description", ""),
                        "confidence": finding.get("confidence", 0),
                    }
                    report_findings.append(finding_data)
                    all_texts.append(chunk_content)

                findings_by_report[report_id] = report_findings

            except Exception as e:
                print(f"❌ Error processing {json_file.name}: {e}")

    return findings_by_report, all_texts


def write_markdown_report(findings_by_report: dict, all_texts: list, output_path: Path):
    """Write findings to markdown file."""

    # Calculate stats
    total_findings = sum(len(f) for f in findings_by_report.values())

    # Calculate phrase frequency
    all_ngrams = []
    for text in all_texts:
        all_ngrams.extend(extract_ngrams(text, n=2))
        all_ngrams.extend(extract_ngrams(text, n=3))

    phrase_counts = Counter(all_ngrams)
    top_phrases = phrase_counts.most_common(20)

    with open(output_path, "w", encoding="utf-8") as f:
        # Header
        f.write("# Other Findings Analysis\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Total Reports:** {len(findings_by_report)}\n")
        f.write(f"**Total 'Other' Findings:** {total_findings}\n\n")

        # Summary table
        f.write("## Summary by Report\n\n")
        f.write("| Report | Count | Avg Severity |\n")
        f.write("|--------|-------|-------------|\n")

        for report_id, findings in sorted(findings_by_report.items()):
            severity_map = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
            avg_sev = sum(severity_map.get(f["severity"], 0) for f in findings) / len(findings)
            avg_sev_label = ["unknown", "low", "medium", "high", "critical"][round(avg_sev)]
            f.write(f"| {report_id[:60]} | {len(findings)} | {avg_sev_label} |\n")

        f.write("\n")

        # Top phrases
        f.write("## Common Phrases in 'Other' Findings\n\n")
        f.write("These phrases appear frequently and may indicate patterns for new categories:\n\n")
        f.write("| Phrase | Count |\n")
        f.write("|--------|-------|\n")
        for phrase, count in top_phrases:
            if count >= 3:  # Only show phrases appearing 3+ times
                f.write(f"| {phrase} | {count} |\n")
        f.write("\n")

        # Detailed findings by report
        f.write("## Detailed Findings\n\n")

        for report_id, findings in sorted(findings_by_report.items()):
            f.write(f"### {report_id}\n\n")
            f.write(f"**Count:** {len(findings)} findings\n\n")

            for i, finding in enumerate(findings, 1):
                f.write("---\n\n")
                f.write(f"**Finding {i}**\n\n")
                f.write(f"**Section:** {finding['section']}\n\n")
                f.write(f"**Severity:** {finding['severity']} | **Monetary:** {finding['monetary']}\n\n")
                f.write(f"**Confidence:** {finding['confidence']:.2f}\n\n")

                # Chunk content (first 500 chars)
                content = finding['chunk_content']
                if len(content) > 500:
                    content = content[:500] + "..."
                content = content.replace("\n", " ").strip()
                f.write(f"**Text:** {content}\n\n")

                f.write(f"*chunk_id: {finding['source_chunk_id']}*\n\n")

            f.write("\n")

    print(f"✅ Report written to: {output_path}")


def main():
    print("=" * 60)
    print("  Extract 'Other' Findings Analysis")
    print("=" * 60)
    print()

    # Directories to scan
    data_dirs = [
        "data/processed/state",
        "data/processed/local_body"
    ]

    # Process reports
    findings_by_report, all_texts = process_reports(data_dirs)

    if not findings_by_report:
        print("❌ No 'other' findings found in any reports")
        return

    # Ensure logs directory exists
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Write report
    output_path = logs_dir / "other_findings_analysis.md"
    write_markdown_report(findings_by_report, all_texts, output_path)

    # Print summary
    print()
    print("=" * 60)
    print("  Summary Statistics")
    print("=" * 60)
    print()

    total = sum(len(f) for f in findings_by_report.values())
    print(f"📊 Total 'other' findings: {total}")
    print(f"📊 Reports with 'other' findings: {len(findings_by_report)}")
    print()

    print("📊 Findings per report:")
    for report_id, findings in sorted(findings_by_report.items(), key=lambda x: -len(x[1])):
        print(f"   {len(findings):3d} - {report_id[:55]}")

    # Top phrases
    all_ngrams = []
    for text in all_texts:
        all_ngrams.extend(extract_ngrams(text, n=2))
        all_ngrams.extend(extract_ngrams(text, n=3))

    phrase_counts = Counter(all_ngrams)
    top_phrases = phrase_counts.most_common(10)

    print()
    print("📊 Top phrases in 'other' findings:")
    for phrase, count in top_phrases:
        if count >= 3:
            print(f"   {count:3d}x - '{phrase}'")

    print()
    print(f"✅ Full analysis saved to: {output_path}")


if __name__ == "__main__":
    main()
