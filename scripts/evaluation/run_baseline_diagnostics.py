"""
Pipeline Quality Diagnostic v3
Standalone — no external dependencies beyond stdlib.
Runs against *_chunks.json files and optionally raw PDFs.

Usage:
    python run_pipeline_diagnostics.py [data_dir] [--pdf-dir PDF_DIR]

Checks:
  1. Hierarchy health        (depth, concentration, child↔parent sync)
  2. Structured table data    (coverage, cell quality, column classification)
  3. Semantic enrichment      (findings, recommendations, entities)
  4. Cross-references         (resolution rate, link quality)
  5. Content integrity        (garbage, empty, page ordering)
  6. PDF ground truth         (page count match, table count sanity) [optional]
"""

import json
import re
import sys
import os
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ─── CONFIGURATION ───────────────────────────────────────────────────────────

THRESHOLDS = {
    # Hierarchy
    "hierarchy_mismatch_warn": 1,  # any mismatches = warn
    "hierarchy_mismatch_fail": 5,  # >5% = fail
    "concentration_warn": 20,  # >20% children under one parent
    "concentration_fail": 40,
    "depth_diversity_warn": 1,  # only 1 depth level = warn
    "unique_hierarchy_min": 5,  # fewer = likely broken scaffolding
    # Structured data
    "table_structured_coverage_warn": 80,  # <80% tables with structured_data
    "table_structured_coverage_fail": 50,
    "cell_empty_rate_warn": 30,  # >30% empty cells
    "cell_empty_rate_fail": 50,
    # Entities
    "entity_noise_warn": 5,  # >5% noisy entities
    "entity_noise_fail": 15,
    # Recommendations
    "rec_fp_rate_warn": 30,  # >30% verb recs likely FP
    "rec_fp_rate_fail": 60,
    # Content
    "garbage_chunk_warn": 5,  # >5% chunks with <10 chars
    "garbage_chunk_fail": 10,
    "page_inversion_warn": 2,  # >2% parents with start > end page
    "page_inversion_fail": 10,
}


# ─── ENTITY NOISE DETECTION ─────────────────────────────────────────────────

NOISE_PATTERNS = [
    re.compile(r"^\d"),  # starts with number
    re.compile(r"^[a-z]"),  # starts lowercase (sentence fragment)
    re.compile(r"\b(audit|noticed|noted|observed|found that)\b", re.I),
    re.compile(r"\b(per cent|percent|below|above)\b", re.I),
    re.compile(r"\b(as per|refer to|we noted)\b", re.I),
    re.compile(r"\b(Chapter|Section|Table|Annexure|Para)\s+\d", re.I),
]


def is_noisy_entity(name: str) -> bool:
    if len(name) < 3 or len(name) > 80:
        return True
    return any(p.search(name) for p in NOISE_PATTERNS)


# ─── VERB REC FALSE POSITIVE DETECTION ───────────────────────────────────────

FP_INDICATORS = [
    re.compile(r"\b(Act|Rules?|Manual|Agreement|Clause|Section\s+\d)\b"),
    re.compile(
        r"\b(provided\s+that|as\s+per|in\s+accordance|stipulated|prescribed)\b", re.I
    ),
    re.compile(r"\b(prior\s+to|it\s+provided|it\s+stipulated)\b", re.I),
]

REAL_REC_INDICATORS = [
    re.compile(r"\b(Audit|CAG)\s+recommend", re.I),
    re.compile(
        r"\b(CBDT|Ministry|MoRTH|NHAI|Government|Department)\s+(may|should)", re.I
    ),
    re.compile(r"•\s*(The\s+)?(CBDT|Ministry|MoRTH)", re.I),
]


def is_likely_fp_verb_rec(text: str) -> bool:
    """Heuristic: is this verb rec likely a false positive?"""
    first_150 = text[:150]
    has_fp = any(p.search(first_150) for p in FP_INDICATORS)
    has_real = any(p.search(text[:200]) for p in REAL_REC_INDICATORS)
    if has_real:
        return False
    return has_fp


# ─── SINGLE REPORT DIAGNOSTIC ───────────────────────────────────────────────


def diagnose_report(data: dict, pdf_page_count: Optional[int] = None) -> dict:
    """Run all diagnostics on a single report JSON."""
    parents = data.get("parent_chunks", [])
    children = data.get("child_chunks", [])
    enrichment = data.get("semantic_enrichment", {})
    registry = data.get("visual_asset_registry", {})
    parent_map = {p["chunk_id"]: p for p in parents}

    result = {
        "report_id": data.get("report_metadata", {}).get("report_id", "unknown"),
        "counts": {},
        "hierarchy": {},
        "structured_data": {},
        "findings": {},
        "recommendations": {},
        "entities": {},
        "cross_references": {},
        "content": {},
        "issues": [],
        "score": 0,
    }

    n_parents = len(parents)
    n_children = len(children)
    result["counts"] = {"parents": n_parents, "children": n_children}

    # ── 1. HIERARCHY ────────────────────────────────────────────────────────

    h_strs = [json.dumps(c.get("hierarchy", {}), sort_keys=True) for c in children]
    unique_h = len(set(h_strs))
    depths = Counter(len(c.get("hierarchy", {})) for c in children)
    parent_counts = Counter(c.get("parent_chunk_id", "") for c in children)
    max_parent_id = parent_counts.most_common(1)[0][0] if parent_counts else ""
    max_conc = parent_counts.most_common(1)[0][1] / max(n_children, 1) * 100

    # Child↔Parent hierarchy sync
    mismatches = 0
    mismatch_types = Counter()
    for c in children:
        p = parent_map.get(c.get("parent_chunk_id", ""), {})
        ch, ph = c.get("hierarchy", {}), p.get("hierarchy", {})
        if ch != ph:
            mismatches += 1
            ch_keys, ph_keys = set(ch.keys()), set(ph.keys())
            if ch_keys < ph_keys:
                mismatch_types["child_missing_keys"] += 1
            elif ch_keys > ph_keys:
                mismatch_types["child_extra_keys"] += 1
            else:
                mismatch_types["value_differs"] += 1

    mismatch_rate = mismatches / max(n_children, 1) * 100

    # Orphan detection
    orphans = sum(1 for c in children if c.get("parent_chunk_id", "") not in parent_map)

    result["hierarchy"] = {
        "unique_values": unique_h,
        "depth_distribution": dict(sorted(depths.items())),
        "depth_levels": len(depths),
        "max_concentration_pct": round(max_conc, 1),
        "top_parent": parent_map.get(max_parent_id, {}).get("toc_entry", "")[:60],
        "mismatches": mismatches,
        "mismatch_rate_pct": round(mismatch_rate, 1),
        "mismatch_types": dict(mismatch_types),
        "orphans": orphans,
    }

    if mismatch_rate > THRESHOLDS["hierarchy_mismatch_fail"]:
        result["issues"].append(
            (
                "CRITICAL",
                "HIERARCHY_DESYNC",
                f"{mismatches} children ({mismatch_rate:.1f}%) have hierarchy ≠ parent's hierarchy",
            )
        )
    elif mismatches > 0:
        result["issues"].append(
            (
                "WARN",
                "HIERARCHY_DESYNC",
                f"{mismatches} children ({mismatch_rate:.1f}%) have hierarchy ≠ parent's hierarchy",
            )
        )

    if max_conc > THRESHOLDS["concentration_fail"]:
        result["issues"].append(
            (
                "CRITICAL",
                "HIERARCHY_CONCENTRATION",
                f"{max_conc:.0f}% children under single parent — section-scoped retrieval broken",
            )
        )
    elif max_conc > THRESHOLDS["concentration_warn"]:
        result["issues"].append(
            (
                "WARN",
                "HIERARCHY_CONCENTRATION",
                f"{max_conc:.0f}% children under single parent",
            )
        )

    if unique_h < THRESHOLDS["unique_hierarchy_min"]:
        result["issues"].append(
            (
                "CRITICAL",
                "HIERARCHY_COLLAPSED",
                f"Only {unique_h} unique hierarchy values — scaffolding likely broken",
            )
        )

    if len(depths) == 1:
        result["issues"].append(
            (
                "WARN",
                "HIERARCHY_FLAT",
                f"All chunks at depth {list(depths.keys())[0]} — no nesting",
            )
        )

    # ── 2. STRUCTURED TABLE DATA ────────────────────────────────────────────

    tables = [c for c in children if c.get("content_type") == "table_markdown"]
    has_sd = [t for t in tables if t.get("structured_data")]
    coverage = len(has_sd) / max(len(tables), 1) * 100

    sd_stats = {
        "total_cells": 0,
        "empty_cells": 0,
        "text_cells": 0,
        "currency_cells": 0,
        "date_cells": 0,
        "col_types": Counter(),
        "with_monetary": 0,
        "with_time": 0,
        "with_entities": 0,
        "with_totals": 0,
        "multi_page": 0,
    }

    for t in has_sd:
        sd = t["structured_data"]
        if sd.get("monetary_unit"):
            sd_stats["with_monetary"] += 1
        if sd.get("time_periods_covered"):
            sd_stats["with_time"] += 1
        if sd.get("entities_covered"):
            sd_stats["with_entities"] += 1
        if sd.get("has_totals"):
            sd_stats["with_totals"] += 1
        if sd.get("is_multi_page"):
            sd_stats["multi_page"] += 1
        for col in sd.get("columns", []):
            sd_stats["col_types"][col.get("column_type", "unknown")] += 1
        for row in sd.get("rows", []):
            for cell in row.get("cells", []):
                sd_stats["total_cells"] += 1
                dt = cell.get("data_type", "")
                if dt == "empty":
                    sd_stats["empty_cells"] += 1
                elif dt == "currency":
                    sd_stats["currency_cells"] += 1
                elif dt in ("date", "fiscal_year"):
                    sd_stats["date_cells"] += 1
                else:
                    sd_stats["text_cells"] += 1

    empty_cell_rate = sd_stats["empty_cells"] / max(sd_stats["total_cells"], 1) * 100

    result["structured_data"] = {
        "total_tables": len(tables),
        "with_structured_data": len(has_sd),
        "coverage_pct": round(coverage, 1),
        "total_cells": sd_stats["total_cells"],
        "empty_cell_pct": round(empty_cell_rate, 1),
        "currency_cells": sd_stats["currency_cells"],
        "date_cells": sd_stats["date_cells"],
        "col_types": dict(sd_stats["col_types"]),
        "tables_with_monetary": sd_stats["with_monetary"],
        "tables_with_time": sd_stats["with_time"],
        "tables_with_entities": sd_stats["with_entities"],
        "tables_with_totals": sd_stats["with_totals"],
        "multi_page_stitched": sd_stats["multi_page"],
    }

    if len(tables) > 0 and coverage < THRESHOLDS["table_structured_coverage_fail"]:
        result["issues"].append(
            (
                "CRITICAL",
                "TABLE_NO_STRUCTURED",
                f"Only {coverage:.0f}% of tables have structured_data",
            )
        )
    elif len(tables) > 0 and coverage < THRESHOLDS["table_structured_coverage_warn"]:
        result["issues"].append(
            (
                "WARN",
                "TABLE_LOW_STRUCTURED",
                f"{coverage:.0f}% of tables have structured_data",
            )
        )

    if empty_cell_rate > THRESHOLDS["cell_empty_rate_fail"]:
        result["issues"].append(
            (
                "WARN",
                "TABLE_EMPTY_CELLS",
                f"{empty_cell_rate:.0f}% of cells are empty — possible OCR/parsing issues",
            )
        )

    # ── 3. FINDINGS ─────────────────────────────────────────────────────────

    findings = enrichment.get("findings", [])
    f_types = Counter(f.get("finding_type", "") for f in findings)
    f_sevs = Counter(f.get("severity", "") for f in findings)
    f_with_money = sum(1 for f in findings if f.get("total_amount_inr", 0) > 0)
    f_with_conf = [f for f in findings if f.get("confidence", 0) > 0]
    avg_conf = sum(f["confidence"] for f in f_with_conf) / max(len(f_with_conf), 1)
    low_conf = sum(1 for f in f_with_conf if f["confidence"] < 0.5)
    f_with_patterns = sum(1 for f in findings if f.get("pattern_types"))

    # Chapter assignment quality — are findings spread across chapters or all in one?
    f_chapters = Counter(f.get("chapter", "") for f in findings)
    top_chapter_pct = (
        f_chapters.most_common(1)[0][1] / max(len(findings), 1) * 100 if findings else 0
    )

    result["findings"] = {
        "total": len(findings),
        "types": dict(f_types),
        "severity": dict(f_sevs),
        "with_monetary": f_with_money,
        "with_confidence": len(f_with_conf),
        "avg_confidence": round(avg_conf, 3),
        "low_confidence_count": low_conf,
        "with_patterns": f_with_patterns,
        "top_chapter_concentration_pct": round(top_chapter_pct, 1),
    }

    if top_chapter_pct > 90 and len(findings) > 10:
        result["issues"].append(
            (
                "WARN",
                "FINDINGS_SINGLE_CHAPTER",
                f"{top_chapter_pct:.0f}% of findings assigned to '{f_chapters.most_common(1)[0][0][:40]}' — chapter assignment may be too broad",
            )
        )

    # ── 4. RECOMMENDATIONS ──────────────────────────────────────────────────

    recs = enrichment.get("recommendations", [])
    r_strats = Counter(r.get("extraction_strategy", "unknown") for r in recs)
    r_numbered = [r for r in recs if r.get("extraction_strategy") == "numbered"]
    r_verb = [r for r in recs if r.get("extraction_strategy") == "verb"]
    r_structural = [r for r in recs if r.get("extraction_strategy") == "structural"]

    # FP analysis for verb recs
    verb_fps = sum(1 for r in r_verb if is_likely_fp_verb_rec(r.get("text", "")))
    verb_fp_rate = verb_fps / max(len(r_verb), 1) * 100

    # Structural recs without action verbs
    structural_no_action = sum(
        1
        for r in r_structural
        if not any(
            w in r.get("text", "").lower()
            for w in [
                "should",
                "may",
                "must",
                "recommend",
                "ensure",
                "consider",
                "examine",
                "review",
            ]
        )
    )

    r_with_entity = sum(1 for r in recs if r.get("target_entity"))
    r_with_action = sum(1 for r in recs if r.get("action_required"))
    r_with_num = sum(1 for r in recs if r.get("rec_number"))

    # Numbered rec completeness — check for gaps
    rec_numbers = sorted(
        [r.get("rec_number", "") for r in r_numbered if r.get("rec_number")]
    )
    # Extract digits from "Recommendation No. X"
    num_digits = []
    for rn in rec_numbers:
        m = re.search(r"(\d+)", str(rn))
        if m:
            num_digits.append(int(m.group(1)))
    num_gaps = []
    if num_digits:
        expected = set(range(min(num_digits), max(num_digits) + 1))
        actual = set(num_digits)
        num_gaps = sorted(expected - actual)

    result["recommendations"] = {
        "total": len(recs),
        "strategies": dict(r_strats),
        "numbered_count": len(r_numbered),
        "numbered_gaps": num_gaps[:10],
        "verb_count": len(r_verb),
        "verb_likely_fp": verb_fps,
        "verb_fp_rate_pct": round(verb_fp_rate, 1),
        "structural_count": len(r_structural),
        "structural_no_action": structural_no_action,
        "with_target_entity": r_with_entity,
        "with_action_required": r_with_action,
        "with_rec_number": r_with_num,
    }

    if verb_fp_rate > THRESHOLDS["rec_fp_rate_fail"]:
        result["issues"].append(
            (
                "WARN",
                "REC_HIGH_FP",
                f"{verb_fps}/{len(r_verb)} verb recs ({verb_fp_rate:.0f}%) look like false positives",
            )
        )
    if num_gaps:
        result["issues"].append(
            ("INFO", "REC_NUMBERED_GAPS", f"Numbered rec gaps: {num_gaps[:5]}")
        )

    # ── 5. ENTITIES ─────────────────────────────────────────────────────────

    entities = enrichment.get("entities", {})
    ent_total = 0
    ent_noisy = 0
    ent_detail = {}
    for etype in ["organizations", "schemes", "ministries"]:
        elist = entities.get(etype, [])
        noisy = [e for e in elist if is_noisy_entity(e)]
        ent_total += len(elist)
        ent_noisy += len(noisy)
        ent_detail[etype] = {
            "total": len(elist),
            "noisy": len(noisy),
            "noise_samples": noisy[:5],
        }

    noise_rate = ent_noisy / max(ent_total, 1) * 100

    result["entities"] = {
        "total": ent_total,
        "noisy": ent_noisy,
        "noise_rate_pct": round(noise_rate, 1),
        "by_type": ent_detail,
    }

    if noise_rate > THRESHOLDS["entity_noise_fail"]:
        result["issues"].append(
            (
                "WARN",
                "ENTITY_NOISY",
                f"{noise_rate:.0f}% of entities are noisy ({ent_noisy}/{ent_total})",
            )
        )
    elif noise_rate > THRESHOLDS["entity_noise_warn"]:
        result["issues"].append(
            ("INFO", "ENTITY_SOME_NOISE", f"{noise_rate:.0f}% entity noise rate")
        )

    # ── 6. CROSS-REFERENCES ─────────────────────────────────────────────────

    xrefs = enrichment.get("cross_references", [])
    annexure_links = enrichment.get("annexure_links", [])
    xref_resolved = sum(1 for x in xrefs if x.get("resolved"))
    ann_resolved = sum(1 for a in annexure_links if a.get("resolved"))
    total_links = len(xrefs) + len(annexure_links)
    total_resolved = xref_resolved + ann_resolved
    resolution_rate = total_resolved / max(total_links, 1) * 100

    temporal = enrichment.get("temporal_coverage", {})
    has_temporal_chunks = sum(1 for c in children if c.get("temporal_references"))

    result["cross_references"] = {
        "cross_refs": len(xrefs),
        "cross_refs_resolved": xref_resolved,
        "annexure_links": len(annexure_links),
        "annexure_links_resolved": ann_resolved,
        "resolution_rate_pct": round(resolution_rate, 1),
        "temporal_audit_period": temporal.get("audit_period"),
        "temporal_ref_years": len(temporal.get("reference_years", [])),
        "chunks_with_temporal": has_temporal_chunks,
    }

    # ── 7. CONTENT INTEGRITY ────────────────────────────────────────────────

    ctypes = Counter(c.get("content_type", "") for c in children)
    empty_chunks = sum(1 for c in children if len(c.get("content", "").strip()) < 10)
    empty_rate = empty_chunks / max(n_children, 1) * 100
    avg_len = sum(len(c.get("content", "")) for c in children) / max(n_children, 1)

    # Page ordering — inversions in parent page ranges
    inversions = 0
    for p in parents:
        pr = p.get("page_range_physical", [])
        if isinstance(pr, (list, tuple)) and len(pr) >= 2:
            if pr[0] > pr[1]:
                inversions += 1
    inversion_rate = inversions / max(n_parents, 1) * 100

    # Extraction confidence
    confs = [
        c.get("extraction_confidence")
        for c in children
        if c.get("extraction_confidence") is not None
    ]
    avg_conf_chunk = sum(confs) / max(len(confs), 1) if confs else 0
    low_conf_chunks = sum(1 for c in confs if c < 0.7)

    result["content"] = {
        "content_types": dict(ctypes),
        "empty_chunks": empty_chunks,
        "empty_rate_pct": round(empty_rate, 1),
        "avg_content_length": round(avg_len),
        "page_inversions": inversions,
        "inversion_rate_pct": round(inversion_rate, 1),
        "chunks_with_confidence": len(confs),
        "avg_extraction_confidence": round(avg_conf_chunk, 3),
        "low_confidence_chunks": low_conf_chunks,
        "visual_registry_tables": registry.get("total_tables", 0),
        "visual_registry_figures": registry.get("total_figures", 0),
    }

    if empty_rate > THRESHOLDS["garbage_chunk_fail"]:
        result["issues"].append(
            ("WARN", "CONTENT_EMPTY", f"{empty_rate:.1f}% of chunks have <10 chars")
        )
    if inversion_rate > THRESHOLDS["page_inversion_fail"]:
        result["issues"].append(
            (
                "WARN",
                "PAGE_INVERSIONS",
                f"{inversion_rate:.1f}% of parents have start > end page",
            )
        )

    # ── 8. PDF GROUND TRUTH (optional) ──────────────────────────────────────

    if pdf_page_count:
        max_page = max((c.get("source_page_physical", 0) for c in children), default=0)
        page_coverage = max_page / pdf_page_count * 100
        result["pdf_validation"] = {
            "pdf_pages": pdf_page_count,
            "max_chunk_page": max_page,
            "page_coverage_pct": round(page_coverage, 1),
        }
        if page_coverage < 80:
            result["issues"].append(
                (
                    "WARN",
                    "LOW_PDF_COVERAGE",
                    f"Chunks only cover {page_coverage:.0f}% of PDF pages ({max_page}/{pdf_page_count})",
                )
            )

    # ── SCORING ─────────────────────────────────────────────────────────────

    score = 100
    for severity, _, _ in result["issues"]:
        if severity == "CRITICAL":
            score -= 15
        elif severity == "WARN":
            score -= 5
        elif severity == "INFO":
            score -= 1
    result["score"] = max(0, score)

    return result


# ─── PRINTING ────────────────────────────────────────────────────────────────


def severity_icon(sev):
    return {"CRITICAL": "🔴", "WARN": "🟡", "INFO": "ℹ️"}.get(sev, "·")


def grade(score):
    if score >= 90:
        return "🟢 EXCELLENT"
    if score >= 75:
        return "🟢 GOOD"
    if score >= 60:
        return "🟡 FAIR"
    return "🔴 POOR"


def pct_icon(val, warn, fail, invert=False):
    if invert:
        if val <= fail:
            return "🔴"
        if val <= warn:
            return "🟡"
        return "🟢"
    if val >= fail:
        return "🔴"
    if val >= warn:
        return "🟡"
    return "🟢"


def print_report(r: dict):
    """Pretty-print a single report diagnostic."""
    print(f"\n{'━' * 70}")
    print(f"  📄 {r['report_id']}")
    print(f"     {r['counts']['parents']} parents, {r['counts']['children']} children")
    print(f"{'━' * 70}")

    h = r["hierarchy"]
    print(f"\n  1. HIERARCHY")
    print(
        f"     {pct_icon(h['mismatch_rate_pct'], 1, 5)} Child↔Parent sync:     {h['mismatches']} mismatches ({h['mismatch_rate_pct']}%)"
    )
    print(
        f"     {'🟢' if h['unique_values'] >= 10 else '🟡' if h['unique_values'] >= 5 else '🔴'} Unique hierarchies:    {h['unique_values']}"
    )
    print(
        f"     {pct_icon(h['max_concentration_pct'], 20, 40)} Max concentration:     {h['max_concentration_pct']}% → '{h['top_parent'][:45]}'"
    )
    print(
        f"     {'🟢' if h['depth_levels'] > 1 else '🟡'} Depth levels:          {h['depth_levels']} — {h['depth_distribution']}"
    )
    if h["orphans"]:
        print(
            f"     🔴 Orphans:               {h['orphans']} children have no valid parent"
        )

    sd = r["structured_data"]
    print(f"\n  2. STRUCTURED TABLE DATA")
    if sd["total_tables"] == 0:
        print(f"     ℹ️  No tables in this report")
    else:
        print(
            f"     {pct_icon(sd['coverage_pct'], 80, 50, invert=True)} Coverage:              {sd['with_structured_data']}/{sd['total_tables']} ({sd['coverage_pct']}%)"
        )
        print(
            f"     {'🟢' if sd['total_cells'] > 0 else '🟡'} Queryable cells:       {sd['total_cells']:,}"
        )
        if sd["total_cells"] > 0:
            print(
                f"     {pct_icon(sd['empty_cell_pct'], 30, 50)} Cell quality:          {sd['empty_cell_pct']}% empty, {sd['currency_cells']} currency, {sd['date_cells']} date"
            )
            print(f"       Column types:           {sd['col_types']}")
            print(
                f"       Metadata:               {sd['tables_with_monetary']} monetary, {sd['tables_with_time']} temporal, {sd['tables_with_entities']} entity, {sd['tables_with_totals']} totals, {sd['multi_page_stitched']} multi-page"
            )

    f = r["findings"]
    print(f"\n  3. FINDINGS")
    if f["total"] == 0:
        print(f"     🟡 No findings extracted")
    else:
        print(
            f"     {'🟢' if f['total'] >= 10 else '🟡'} Count:                 {f['total']}"
        )
        print(f"       Types:                  {f['types']}")
        print(f"       Severity:               {f['severity']}")
        print(
            f"     {'🟢' if f['with_monetary'] > 0 else '🟡'} With monetary:         {f['with_monetary']}/{f['total']}"
        )
        print(
            f"     {'🟢' if f['with_confidence'] > 0 else '🟡'} With confidence:       {f['with_confidence']}/{f['total']} (avg {f['avg_confidence']:.2f}, {f['low_confidence_count']} low)"
        )
        print(
            f"     {'🟢' if f['with_patterns'] > 0 else '🟡'} With patterns:         {f['with_patterns']}/{f['total']}"
        )
        if f["top_chapter_concentration_pct"] > 80:
            print(
                f"     🟡 Chapter spread:        {f['top_chapter_concentration_pct']}% in single chapter"
            )

    rec = r["recommendations"]
    print(f"\n  4. RECOMMENDATIONS")
    if rec["total"] == 0:
        print(f"     🟡 No recommendations extracted")
    else:
        print(
            f"     {'🟢' if rec['total'] >= 5 else '🟡'} Count:                 {rec['total']} — {rec['strategies']}"
        )
        if rec["numbered_count"]:
            gaps_str = (
                f" (gaps: {rec['numbered_gaps'][:5]})"
                if rec["numbered_gaps"]
                else " (no gaps ✓)"
            )
            print(f"     🟢 Numbered:              {rec['numbered_count']}{gaps_str}")
        if rec["verb_count"]:
            fp_icon = pct_icon(rec["verb_fp_rate_pct"], 30, 60)
            print(
                f"     {fp_icon} Verb:                 {rec['verb_count']} ({rec['verb_likely_fp']} likely FP, {rec['verb_fp_rate_pct']}%)"
            )
        if rec["structural_count"]:
            print(
                f"     {'🟡' if rec['structural_no_action'] else '🟢'} Structural:            {rec['structural_count']} ({rec['structural_no_action']} without action verb)"
            )
        print(
            f"       Enrichment:             entity={rec['with_target_entity']}, action={rec['with_action_required']}, rec_number={rec['with_rec_number']}"
        )

    ent = r["entities"]
    print(f"\n  5. ENTITIES")
    if ent["total"] == 0:
        print(f"     🟡 No entities extracted")
    else:
        print(
            f"     {pct_icon(ent['noise_rate_pct'], 5, 15)} Noise rate:            {ent['noisy']}/{ent['total']} ({ent['noise_rate_pct']}%)"
        )
        for etype, detail in ent["by_type"].items():
            if detail["total"] > 0:
                noise_str = (
                    f" ⚠ {detail['noise_samples'][:3]}" if detail["noisy"] else ""
                )
                print(
                    f"       {etype:<20} {detail['total']:>4} ({detail['noisy']} noisy){noise_str}"
                )

    xr = r["cross_references"]
    print(f"\n  6. CROSS-REFERENCES & TEMPORAL")
    total_links = xr["cross_refs"] + xr["annexure_links"]
    if total_links == 0:
        print(f"     🟡 No cross-references detected")
    else:
        print(
            f"     {pct_icon(xr['resolution_rate_pct'], 30, 15, invert=True)} Resolution:            {xr['cross_refs_resolved'] + xr['annexure_links_resolved']}/{total_links} ({xr['resolution_rate_pct']}%)"
        )
        print(
            f"       Cross-refs:             {xr['cross_refs']} ({xr['cross_refs_resolved']} resolved)"
        )
        if xr["annexure_links"]:
            print(
                f"       Annexure links:         {xr['annexure_links']} ({xr['annexure_links_resolved']} resolved)"
            )
    audit_period = xr.get("temporal_audit_period")
    if audit_period and isinstance(audit_period, dict):
        print(
            f"     🟢 Audit period:          {audit_period.get('start_year')}-{audit_period.get('end_year')}"
        )
    elif xr["temporal_ref_years"] > 0:
        print(
            f"     🟡 No audit period, but {xr['temporal_ref_years']} reference years detected"
        )
    print(f"       Chunks with temporal:   {xr['chunks_with_temporal']}")

    ct = r["content"]
    print(f"\n  7. CONTENT INTEGRITY")
    print(
        f"     {pct_icon(ct['empty_rate_pct'], 5, 10)} Empty chunks:          {ct['empty_chunks']} ({ct['empty_rate_pct']}%)"
    )
    print(
        f"     {pct_icon(ct['inversion_rate_pct'], 2, 10)} Page inversions:       {ct['page_inversions']} ({ct['inversion_rate_pct']}%)"
    )
    print(f"       Avg content length:     {ct['avg_content_length']} chars")
    print(f"       Content types:          {ct['content_types']}")
    if ct["chunks_with_confidence"]:
        print(
            f"     {'🟢' if ct['avg_extraction_confidence'] > 0.85 else '🟡'} Avg confidence:        {ct['avg_extraction_confidence']:.3f} ({ct['low_confidence_chunks']} low)"
        )
    print(
        f"       Visual registry:        {ct['visual_registry_tables']} tables, {ct['visual_registry_figures']} figures"
    )

    if r.get("pdf_validation"):
        pv = r["pdf_validation"]
        print(f"\n  8. PDF GROUND TRUTH")
        print(
            f"     {pct_icon(pv['page_coverage_pct'], 80, 60, invert=True)} Page coverage:         {pv['max_chunk_page']}/{pv['pdf_pages']} ({pv['page_coverage_pct']}%)"
        )

    # Issues
    issues = r["issues"]
    if issues:
        print(f"\n  ⚡ ISSUES ({len(issues)})")
        for sev, code, detail in issues:
            print(f"     {severity_icon(sev)} [{sev}] {code}: {detail}")

    print(f"\n  {'─' * 50}")
    print(f"  🏆 SCORE: {r['score']}/100 [{grade(r['score'])}]")


def print_corpus_summary(results: list):
    """Print cross-report summary."""
    n = len(results)
    print(f"\n{'━' * 70}")
    print(f"  📊 CORPUS SUMMARY — {n} REPORTS")
    print(f"{'━' * 70}")

    avg = lambda key, sub: sum(r[sub].get(key, 0) for r in results) / n

    # Hierarchy
    avg_conc = avg("max_concentration_pct", "hierarchy")
    avg_unique = sum(r["hierarchy"]["unique_values"] for r in results) / n
    total_mismatches = sum(r["hierarchy"]["mismatches"] for r in results)
    print(f"\n  HIERARCHY")
    print(
        f"  {pct_icon(avg_conc, 20, 40)} Avg concentration:     {avg_conc:.1f}% (target <20%)"
    )
    print(
        f"  {'🟢' if avg_unique > 50 else '🟡'} Avg unique hierarchies: {avg_unique:.0f}"
    )
    print(
        f"  {'🟢' if total_mismatches == 0 else '🔴'} Total mismatches:      {total_mismatches}"
    )

    # Structured data
    total_tables = sum(r["structured_data"]["total_tables"] for r in results)
    total_sd = sum(r["structured_data"]["with_structured_data"] for r in results)
    total_cells = sum(r["structured_data"]["total_cells"] for r in results)
    cov = total_sd / max(total_tables, 1) * 100
    print(f"\n  STRUCTURED DATA")
    print(
        f"  {pct_icon(cov, 80, 50, invert=True)} Table coverage:        {total_sd}/{total_tables} ({cov:.0f}%)"
    )
    print(
        f"  {'🟢' if total_cells > 0 else '🔴'} Total queryable cells: {total_cells:,}"
    )

    # Findings & Recs
    total_findings = sum(r["findings"]["total"] for r in results)
    total_recs = sum(r["recommendations"]["total"] for r in results)
    total_verb = sum(r["recommendations"]["verb_count"] for r in results)
    total_verb_fp = sum(r["recommendations"]["verb_likely_fp"] for r in results)
    verb_fp_rate = total_verb_fp / max(total_verb, 1) * 100
    print(f"\n  ENRICHMENT")
    print(
        f"  {'🟢' if total_findings > 0 else '🔴'} Findings:              {total_findings} across {sum(1 for r in results if r['findings']['total'] > 0)} reports"
    )
    print(
        f"  {'🟢' if total_recs > 0 else '🔴'} Recommendations:       {total_recs} ({total_verb} verb, {total_verb_fp} likely FP = {verb_fp_rate:.0f}%)"
    )

    # Entities
    total_ents = sum(r["entities"]["total"] for r in results)
    total_noisy = sum(r["entities"]["noisy"] for r in results)
    noise_rate = total_noisy / max(total_ents, 1) * 100
    print(
        f"  {pct_icon(noise_rate, 5, 15)} Entity noise:          {total_noisy}/{total_ents} ({noise_rate:.0f}%)"
    )

    # Cross-refs
    total_xrefs = sum(
        r["cross_references"]["cross_refs"] + r["cross_references"]["annexure_links"]
        for r in results
    )
    total_resolved = sum(
        r["cross_references"]["cross_refs_resolved"]
        + r["cross_references"]["annexure_links_resolved"]
        for r in results
    )
    res_rate = total_resolved / max(total_xrefs, 1) * 100
    print(
        f"  {pct_icon(res_rate, 30, 15, invert=True)} Cross-ref resolution:  {total_resolved}/{total_xrefs} ({res_rate:.0f}%)"
    )

    # Issues
    all_issues = []
    for r in results:
        all_issues.extend(r["issues"])
    crit = sum(1 for s, _, _ in all_issues if s == "CRITICAL")
    warn = sum(1 for s, _, _ in all_issues if s == "WARN")
    info = sum(1 for s, _, _ in all_issues if s == "INFO")
    print(f"\n  ISSUES")
    print(f"  🔴 Critical: {crit}  🟡 Warn: {warn}  ℹ️  Info: {info}")

    if crit > 0:
        print(f"\n  Critical issues:")
        for r in results:
            for sev, code, detail in r["issues"]:
                if sev == "CRITICAL":
                    print(f"    🔴 [{r['report_id'][:40]}] {code}: {detail}")

    avg_score = sum(r["score"] for r in results) / n
    print(f"\n  {'─' * 50}")
    print(f"  📈 CORPUS SCORE: {avg_score:.0f}/100 [{grade(avg_score)}]")
    print(f"     Per report: {', '.join(f'{r["score"]}' for r in results)}")


# ─── OUTPUT CAPTURE ──────────────────────────────────────────────────────────


class TeeOutput:
    """Write to both stdout and a file simultaneously."""

    def __init__(self, file_path: Path):
        self.terminal = sys.stdout
        self.log = open(file_path, 'w', encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


# ─── MAIN ────────────────────────────────────────────────────────────────────


def get_pdf_page_count(pdf_path: Path) -> Optional[int]:
    """Get page count from PDF if available."""
    try:
        with open(pdf_path, "rb") as f:
            content = f.read()
        # Quick regex for /Count in PDF
        matches = re.findall(rb"/Count\s+(\d+)", content)
        if matches:
            return max(int(m) for m in matches)
    except:
        pass
    return None


def main():
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/processed")
    pdf_dir = None
    if "--pdf-dir" in sys.argv:
        idx = sys.argv.index("--pdf-dir")
        if idx + 1 < len(sys.argv):
            pdf_dir = Path(sys.argv[idx + 1])

    json_files = sorted(data_dir.glob("*_chunks.json"))
    if not json_files:
        print(f"❌ No *_chunks.json files found in {data_dir}")
        sys.exit(1)

    # Set up output file in logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%d_%m_%y")
    output_file = logs_dir / f"all_report_diagnostics_{timestamp}.md"

    # Create TeeOutput to write to both stdout and file
    tee = TeeOutput(output_file)
    original_stdout = sys.stdout
    sys.stdout = tee

    try:
        print(f"🔍 Pipeline Diagnostic v3 — {len(json_files)} reports in {data_dir}")
        print(f"📝 Saving results to: {output_file}")
        print(f"{'━' * 70}")

        results = []
        for jf in json_files:
            with open(jf) as f:
                data = json.load(f)

            # Try to find matching PDF
            pdf_pages = None
            if pdf_dir:
                stem = jf.stem.replace("_chunks", "")
                for ext in [".pdf", ".PDF"]:
                    pdf_path = pdf_dir / f"{stem}{ext}"
                    if pdf_path.exists():
                        pdf_pages = get_pdf_page_count(pdf_path)
                        break

            r = diagnose_report(data, pdf_pages)
            r["filename"] = jf.name
            results.append(r)
            print_report(r)

        if len(results) > 1:
            print_corpus_summary(results)

        print()
        print(f"✅ Diagnostic complete! Results saved to: {output_file}")

    finally:
        # Restore original stdout and close file
        sys.stdout = original_stdout
        tee.close()
        print(f"✅ Diagnostic complete! Results saved to: {output_file}")


if __name__ == "__main__":
    main()
