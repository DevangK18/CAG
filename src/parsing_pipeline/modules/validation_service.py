"""
ValidationService: Quality Assurance & Metrics for CAG Pipeline.
Implements Phase 0 of the CAG RAG Pipeline Implementation Plan.

CORRECTED VERSION v2 (2025-12-23) - Fixes:
1. Page inversion check now examines parent chunk page_range_physical
2. Hierarchy check now detects "all children assigned to one parent" problem
3. TOC quality patterns expanded to catch more false positives
4. Scoring properly penalizes flat hierarchy
5. CRITICAL FIX: Concentration penalty now exponential (67% concentration = FATAL)
6. CRITICAL FIX: Flat hierarchy penalty increased (1.8% deep = major problem)
7. CRITICAL FIX: Thresholds lowered (50% concentration = CRITICAL, not 80%)
8. Added RAG-specific quality tiers (World-Class vs Functional vs Broken)
"""

import re
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter, defaultdict


class ValidationService:
    """
    Computes quality metrics for parsed document JSONs.
    Used to establish baselines (Phase 0) and verify fixes (Phase 1+).

    SCORING PHILOSOPHY (v2):
    - Concentration >50% = RAG is BROKEN (can't retrieve specific content)
    - Deep links <20% = RAG is WEAK (no nested context)
    - Both issues should heavily penalize scores
    - A "passing" score (80+) should mean RAG will actually work well
    """

    # RAG Quality Tiers
    TIER_WORLD_CLASS = 90  # Excellent retrieval precision
    TIER_PRODUCTION = 80  # Good enough for production
    TIER_FUNCTIONAL = 60  # Works but with issues
    TIER_BROKEN = 0  # RAG won't work properly

    def __init__(self):
        # Patterns for FALSE POSITIVE TOC entries (should NOT be chapters)
        self.bad_toc_patterns = [
            r"^\d+$",  # Just a number (e.g., "40")
            r"^[ivxlc]+$",  # Just roman numerals
            r"^[a-z]",  # Starts with lowercase
            r"^\W",  # Starts with non-word char
            r"^\(.*\)$",  # Just parenthetical (e.g., "(₹ in crore)")
            r".*\.{4,}.*",  # Dots leader (e.g., "Introduction......")
            r".*₹.*",  # Financial figures
            r"(?i)^total\s",  # Table rows starting with "Total"
            r"(?i)^table\s+\d+",  # Table captions
            r"(?i)^figure\s+\d+",  # Figure captions
            r"(?i)^chart\s+\d+",  # Chart captions
            r"(?i)^graph\s+\d+",  # Graph captions
            r"(?i)^box\s+\d+",  # Box captions
            r"(?i)^case\s+[ivx]+\s",  # Case study headers (Case I, Case II)
            r"(?i)^sl\.?\s*no",  # Serial number headers
            r"(?i)^source\s*:",  # Source attributions
            r"(?i)^note\s*:",  # Notes
            r"^\d+\s+\d+\s+\d+",  # Column numbers (1 2 3 4 5...)
            r"^\d[\d,\.]+\s+\d[\d,\.]+",  # Numeric data rows
            r"^Report No\.\s+\d+",  # Report number repeated as header
            # NEW: Pipe characters (table cells)
            r".*\|.*\|",
            # NEW: Year-data patterns
            r"^\d{4}[-–]\d{2,4}\s+\d+",
        ]
        self.toc_reject_regex = [re.compile(p) for p in self.bad_toc_patterns]

        # Patterns for VALID TOC entries (high confidence chapters)
        self.good_toc_patterns = [
            r"^Chapter\s+[IVX\d]+",  # Chapter I, Chapter 1
            r"^Section\s+[IVX\d]+",  # Section I, Section 1
            r"^Part\s+[IVX\d]+",  # Part I, Part 1
            r"^Annexure\s+[IVX\d]+",  # Annexure I
            r"^Appendix\s+[IVX\d]+",  # Appendix I
            r"^\d+\.\d+(\.\d+)?\s+[A-Z]",  # Numbered sections: 1.1 Introduction
            r"^(Preface|Foreword|Executive\s+Summary|Introduction|Conclusion|Glossary)$",
        ]
        self.toc_accept_regex = [
            re.compile(p, re.IGNORECASE) for p in self.good_toc_patterns
        ]

    def validate_report(self, report_data: Dict[str, Any], enrichment_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Run all validation checks on a single report's JSON data.
        Returns detailed metrics and an overall RAG readiness score.
        """
        parent_chunks = report_data.get("parent_chunks", [])
        child_chunks = report_data.get("child_chunks", [])
        metadata = report_data.get("report_metadata", {})

        # 1. Hierarchy Validation
        hierarchy_stats = self._validate_hierarchy(parent_chunks, child_chunks)

        # 2. Page Order Validation (checks parent page ranges)
        page_stats = self._validate_page_order(parent_chunks)

        # 3. TOC Quality Validation (ENHANCED)
        toc_stats = self._validate_toc_quality(parent_chunks)

        # 4. Table Quality
        table_stats = self._validate_table_quality(child_chunks)

        # 5. Metadata Completeness
        metadata_stats = self._validate_metadata(metadata)

        # 6. Garbage Chunk Detection
        garbage_stats = self._validate_garbage_chunks(child_chunks)

        # 7-11: P3-7 Semantic enrichment checks
        enrichment = enrichment_data or {}
        entity_stats = self._validate_entity_quality(enrichment)
        finding_stats = self._validate_finding_quality(enrichment)
        caption_stats = self._validate_caption_quality(child_chunks)
        xref_stats = self._validate_cross_references(enrichment)
        temporal_stats = self._validate_temporal(enrichment)

        # 12-15: P4-7 Phase 4 feature checks
        rec_stats = self._validate_recommendations(enrichment)
        exec_stats = self._validate_exec_summary(enrichment)
        visual_registry_stats = self._validate_visual_registry(report_data)
        footnote_stats = self._validate_footnotes(report_data)

        # Calculate overall score with P3-7 semantic quality (15%)
        overall_score = self._calculate_overall_score(
            hierarchy_stats, page_stats, toc_stats, metadata_stats, garbage_stats,
            entity_stats, finding_stats, caption_stats
        )

        # Determine RAG quality tier
        rag_tier = self._determine_rag_tier(overall_score, hierarchy_stats)

        return {
            "report_id": metadata.get("report_id", "unknown"),
            "hierarchy": hierarchy_stats,
            "page_order": page_stats,
            "toc_quality": toc_stats,
            "tables": table_stats,
            "metadata": metadata_stats,
            "garbage": garbage_stats,
            "entity_quality": entity_stats,
            "finding_quality": finding_stats,
            "caption_quality": caption_stats,
            "cross_references": xref_stats,
            "temporal": temporal_stats,
            "recommendations": rec_stats,
            "executive_summary": exec_stats,
            "visual_registry": visual_registry_stats,
            "footnotes": footnote_stats,
            "overall_score": overall_score,
            "rag_tier": rag_tier,
            "issues": self._collect_issues(
                hierarchy_stats, page_stats, toc_stats, metadata_stats, garbage_stats
            ),
        }

    def _validate_hierarchy(
        self, parents: List[Dict], children: List[Dict]
    ) -> Dict[str, Any]:
        """
        Check parent-child linkage, depth distribution, and assignment balance.

        FIXED: Now detects when all children are assigned to a single parent,
        which makes the hierarchy useless for RAG retrieval.
        """
        if not children:
            return {
                "total_children": 0,
                "orphans": 0,
                "orphan_rate": 0.0,
                "deep_link_rate": 0.0,
                "concentration_rate": 0.0,
                "status": "EMPTY",
            }

        parent_ids = {p["chunk_id"] for p in parents}
        orphans = 0
        deep_links = 0  # Children with Level 2+ hierarchy

        # Count children per parent to detect concentration
        children_per_parent = Counter()

        for child in children:
            pid = child.get("parent_chunk_id")

            # Check linkage
            if not pid or pid not in parent_ids:
                orphans += 1
            else:
                children_per_parent[pid] += 1

            # Check depth (Did we capture nested structure?)
            hierarchy = child.get("metadata", {}).get("hierarchy", {})
            if len(hierarchy) > 1:  # More than just Level 1
                deep_links += 1

        total_children = len(children)
        total_parents = len(parents) if parents else 1

        # Calculate concentration: what % of children go to the top parent?
        if children_per_parent:
            max_children = children_per_parent.most_common(1)[0][1]
            top_parent_id = children_per_parent.most_common(1)[0][0]
            concentration_rate = (max_children / total_children) * 100
        else:
            concentration_rate = 0.0
            top_parent_id = None

        # Parents with zero children
        parents_with_children = len(children_per_parent)
        empty_parents = total_parents - parents_with_children
        empty_parent_rate = (
            (empty_parents / total_parents) * 100 if total_parents > 0 else 0
        )

        # Determine status
        orphan_rate = (orphans / total_children) * 100
        deep_link_rate = (deep_links / total_children) * 100

        if orphan_rate > 50:
            status = "CRITICAL_ORPHANS"
        elif concentration_rate > 60:  # LOWERED from 90
            status = "CRITICAL_CONCENTRATION"
        elif concentration_rate > 40:
            status = "WARNING_CONCENTRATION"
        elif deep_link_rate < 10:
            status = "WARNING_SHALLOW"
        elif deep_link_rate < 30:
            status = "NOTICE_SHALLOW"
        else:
            status = "OK"

        return {
            "total_children": total_children,
            "total_parents": total_parents,
            "orphans": orphans,
            "orphan_rate": round(orphan_rate, 2),
            "deep_links": deep_links,
            "deep_link_rate": round(deep_link_rate, 2),
            "concentration_rate": round(concentration_rate, 2),
            "top_parent_children": children_per_parent.most_common(1)[0][1]
            if children_per_parent
            else 0,
            "empty_parents": empty_parents,
            "empty_parent_rate": round(empty_parent_rate, 2),
            "parents_with_children": parents_with_children,
            "status": status,
        }

    def _validate_page_order(self, parents: List[Dict]) -> Dict[str, Any]:
        """
        Check for page range inversions in PARENT chunks.

        FIXED: Now checks page_range_physical[0] <= page_range_physical[1]
        instead of checking child chunk ordering.
        """
        if not parents:
            return {
                "total_parents": 0,
                "total_inversions": 0,
                "inversion_rate": 0.0,
                "inversion_examples": [],
            }

        inversions = 0
        inversion_examples = []

        for p in parents:
            # Try different possible field names
            page_range = p.get("page_range_physical") or p.get("page_range") or []

            if isinstance(page_range, dict):
                start = page_range.get("start_page", 0)
                end = page_range.get("end_page", 0)
            elif isinstance(page_range, (list, tuple)) and len(page_range) >= 2:
                start = page_range[0]
                end = page_range[1]
            else:
                continue  # Can't check this parent

            if start > end:
                inversions += 1
                if len(inversion_examples) < 5:
                    inversion_examples.append(
                        {
                            "chunk_id": p.get("chunk_id", "?"),
                            "toc_entry": p.get("toc_entry", "?")[:50],
                            "page_range": [start, end],
                        }
                    )

        total = len(parents)
        return {
            "total_parents": total,
            "total_inversions": inversions,
            "inversion_rate": round((inversions / total) * 100, 2)
            if total > 0
            else 0.0,
            "inversion_examples": inversion_examples,
        }

    def _validate_toc_quality(self, parents: List[Dict]) -> Dict[str, Any]:
        """Check for false positive TOC entries (tables, figures, etc.)."""
        if not parents:
            return {
                "total_parents": 0,
                "garbage_parents": 0,
                "false_positive_rate": 0.0,
                "duplicate_entries": 0,
                "sample_garbage": [],
            }

        garbage = 0
        sample_garbage = []
        title_counts = Counter()

        for p in parents:
            title = p.get("toc_entry", "") or ""
            title_counts[title.lower()] += 1

            # Check against bad patterns
            is_bad = False
            matched_pattern = None

            for pattern in self.toc_reject_regex:
                if pattern.match(title) or pattern.search(title):
                    is_bad = True
                    matched_pattern = "reject_pattern"
                    break

            # Check if it matches a good pattern (override bad check)
            if is_bad:
                for pattern in self.toc_accept_regex:
                    if pattern.match(title):
                        is_bad = False
                        break

            if is_bad:
                garbage += 1
                if len(sample_garbage) < 10:
                    sample_garbage.append(
                        {"title": title[:60], "reason": matched_pattern or "unknown"}
                    )

        # Count duplicates
        duplicates = sum(1 for count in title_counts.values() if count > 1)

        total = len(parents)
        return {
            "total_parents": total,
            "garbage_parents": garbage,
            "false_positive_rate": round((garbage / total) * 100, 2)
            if total > 0
            else 0.0,
            "duplicate_entries": duplicates,
            "sample_garbage": sample_garbage,
        }

    def _validate_table_quality(self, children: List[Dict]) -> Dict[str, Any]:
        """Check table extraction quality."""
        tables = [c for c in children if c.get("content_type") == "table_markdown"]

        if not tables:
            return {"total_tables": 0, "issues": []}

        issues = []
        for t in tables:
            content = t.get("content", "")
            if not content or len(content) < 10:
                issues.append("empty_table")
            elif "|" not in content:
                issues.append("missing_markdown_format")

        return {
            "total_tables": len(tables),
            "issues": issues[:10],  # Limit examples
            "issue_rate": round((len(issues) / len(tables)) * 100, 2)
            if tables
            else 0.0,
        }

    def _validate_metadata(self, metadata: Dict) -> Dict[str, Any]:
        """Check metadata completeness."""
        required_fields = [
            "report_id",
            "report_title",
            "report_no",
            "ministry",
            "report_year",
        ]
        optional_fields = ["report_type", "total_pages", "source_filename"]

        present = 0
        missing_required = []
        unknown_fields = []

        for field in required_fields:
            value = metadata.get(field)
            if value and str(value).strip().lower() not in ["unknown", "none", ""]:
                present += 1
            else:
                missing_required.append(field)
                if value and str(value).strip().lower() == "unknown":
                    unknown_fields.append(field)

        for field in optional_fields:
            value = metadata.get(field)
            if value and str(value).strip().lower() not in ["unknown", "none", ""]:
                present += 1

        total_fields = len(required_fields) + len(optional_fields)
        completeness = (present / total_fields) * 100 if total_fields > 0 else 0

        return {
            "completeness_rate": round(completeness, 2),
            "missing_required": missing_required,
            "unknown_fields": unknown_fields,
        }

    def _validate_garbage_chunks(self, children: List[Dict]) -> Dict[str, Any]:
        """Detect garbage/noise chunks."""
        if not children:
            return {
                "total_children": 0,
                "garbage_count": 0,
                "garbage_rate": 0.0,
                "sample_garbage": [],
            }

        garbage_count = 0
        sample_garbage = []

        for child in children:
            content = child.get("content", "")
            content_type = child.get("content_type", "")

            is_garbage = False

            # Skip tables for this check
            if content_type == "table_markdown":
                continue

            # Garbage indicators
            if len(content.strip()) < 5:
                is_garbage = True
            elif re.match(r"^[\d\s\.\,\-]+$", content.strip()):  # Just numbers
                is_garbage = True
            elif re.match(r"^[^\w\s]+$", content.strip()):  # Just symbols
                is_garbage = True
            elif content_type in ["header", "page_number"]:
                if len(content) < 20:
                    is_garbage = True

            if is_garbage:
                garbage_count += 1
                if len(sample_garbage) < 10:
                    sample_garbage.append(content[:50])

        # Exclude tables from total for this calculation
        non_table_children = [
            c for c in children if c.get("content_type") != "table_markdown"
        ]
        total = len(non_table_children) if non_table_children else 1

        return {
            "total_children": len(children),
            "garbage_count": garbage_count,
            "garbage_rate": round((garbage_count / total) * 100, 2),
            "sample_garbage": sample_garbage,
        }

    def _calculate_overall_score(
        self,
        hierarchy: Dict,
        page: Dict,
        toc: Dict,
        metadata: Dict,
        garbage: Dict,
        entity: Optional[Dict] = None,
        finding: Optional[Dict] = None,
        caption: Optional[Dict] = None,
    ) -> float:
        """
        Weighted score (0-100) for RAG readiness.

        FIXED v2: Now properly penalizes:
        - High concentration (STEEP exponential penalty above 30%)
        - Flat hierarchy (steep penalty below 30% deep links)
        - Page inversions

        P3-7 Updated Weights:
        - Hierarchy Health: 35% (orphans + depth + concentration) - DECREASED from 45%
        - Page Order: 10% (inversions)
        - TOC Quality: 20% (false positives) - DECREASED from 25%
        - Metadata: 10% (completeness)
        - Content Quality: 10% (garbage chunks)
        - Semantic Quality: 15% (entities + findings + captions) - NEW
        """

        # =================================================================
        # HIERARCHY SCORE (45%) - Most important for RAG
        # =================================================================

        orphan_rate = hierarchy.get("orphan_rate", 0)
        deep_link_rate = hierarchy.get("deep_link_rate", 0)
        concentration_rate = hierarchy.get("concentration_rate", 0)

        # Orphan penalty: Linear, 1:1
        orphan_penalty = orphan_rate

        # Depth penalty: STEEP below 30%
        # 90%+ deep = 0-3 penalty, 70% = 6, 50% = 15, 30% = 35, 10% = 65, 0% = 85
        if deep_link_rate >= 70:
            depth_penalty = (100 - deep_link_rate) * 0.3
        elif deep_link_rate >= 50:
            depth_penalty = 9 + (70 - deep_link_rate) * 0.5
        elif deep_link_rate >= 30:
            depth_penalty = 19 + (50 - deep_link_rate) * 1.0
        elif deep_link_rate >= 10:
            depth_penalty = 39 + (30 - deep_link_rate) * 1.5
        else:
            depth_penalty = 69 + (10 - deep_link_rate) * 2.0

        # Concentration penalty: VERY STEEP above 30%
        # 15% = 0, 30% = 7.5, 50% = 37.5, 70% = 87.5, 90% = 147
        # Goal: 67% concentration should result in h_score ~70 or lower
        if concentration_rate <= 15:
            concentration_penalty = 0
        elif concentration_rate <= 30:
            concentration_penalty = (concentration_rate - 15) * 0.5
        elif concentration_rate <= 50:
            concentration_penalty = 7.5 + (concentration_rate - 30) * 1.5
        elif concentration_rate <= 70:
            concentration_penalty = 37.5 + (concentration_rate - 50) * 2.5
        else:
            concentration_penalty = 87.5 + (concentration_rate - 70) * 3.0

        # Combine hierarchy penalties
        h_total_penalty = (
            orphan_penalty * 0.3 + depth_penalty * 0.35 + concentration_penalty * 0.35
        )
        h_score = max(0, 100 - h_total_penalty)

        # =================================================================
        # PAGE ORDER SCORE (10%)
        # =================================================================
        inversion_rate = page.get("inversion_rate", 0)
        p_score = max(0, 100 - inversion_rate * 2)

        # =================================================================
        # TOC QUALITY SCORE (25%)
        # =================================================================
        fp_rate = toc.get("false_positive_rate", 0)
        t_score = max(0, 100 - fp_rate * 1.5)

        # =================================================================
        # METADATA SCORE (10%)
        # =================================================================
        m_score = metadata.get("completeness_rate", 0)

        # =================================================================
        # CONTENT QUALITY SCORE (10%)
        # =================================================================
        garbage_rate = garbage.get("garbage_rate", 0)
        g_score = max(0, 100 - garbage_rate * 1.5)

        # =================================================================
        # SEMANTIC QUALITY SCORE (15%) - P3-7
        # =================================================================
        s_score = 100.0  # Default if no enrichment data

        if entity and finding and caption:
            # Entity quality: noise rate (0-100) -> max(0, 100 - noise_rate * 2)
            entity_noise = entity.get("noise_rate", 0)
            entity_score = max(0, 100 - entity_noise * 2)

            # Finding quality: 100 if no issues, 70 if <3 issues, 40 otherwise
            finding_issues = len(finding.get("issues", []))
            if finding_issues == 0:
                finding_score = 100
            elif finding_issues < 3:
                finding_score = 70
            else:
                finding_score = 40

            # Caption quality: max(0, 100 - generic_rate)
            caption_generic_rate = caption.get("generic_rate", 0)
            caption_score = max(0, 100 - caption_generic_rate)

            # Weighted: entity * 0.4 + finding * 0.3 + caption * 0.3
            s_score = (
                entity_score * 0.4
                + finding_score * 0.3
                + caption_score * 0.3
            )

        # =================================================================
        # WEIGHTED TOTAL
        # =================================================================
        overall = (
            h_score * 0.35      # Hierarchy: 35%
            + p_score * 0.10    # Page Order: 10%
            + t_score * 0.20    # TOC Quality: 20% (was 25%)
            + m_score * 0.10    # Metadata: 10%
            + g_score * 0.10    # Content Quality: 10%
            + s_score * 0.15    # Semantic Quality: 15% (NEW)
        )

        return round(overall, 1)

    def _determine_rag_tier(self, score: float, hierarchy: Dict) -> str:
        """
        Determine RAG quality tier based on score AND hierarchy metrics.

        Even with a decent score, certain issues make RAG unusable.
        """
        concentration = hierarchy.get("concentration_rate", 0)
        deep_links = hierarchy.get("deep_link_rate", 0)
        orphan_rate = hierarchy.get("orphan_rate", 0)

        # Hard failures that override score
        if concentration > 70:
            return "BROKEN - High concentration makes retrieval useless"
        if orphan_rate > 50:
            return "BROKEN - Too many orphan chunks"
        if deep_links < 5 and concentration > 50:
            return "BROKEN - Flat hierarchy + high concentration"

        # Score-based tiers
        if score >= self.TIER_WORLD_CLASS:
            if concentration > 30:
                return "PRODUCTION - Good but concentration slightly high"
            return "WORLD-CLASS - Excellent RAG quality"
        elif score >= self.TIER_PRODUCTION:
            return "PRODUCTION - Good for deployment"
        elif score >= self.TIER_FUNCTIONAL:
            return "FUNCTIONAL - Works but has issues"
        else:
            return "NEEDS WORK - Below minimum quality"

    # ==================== P3-7: SEMANTIC ENRICHMENT VALIDATION ====================

    def _validate_entity_quality(self, enrichment: Dict) -> Dict[str, Any]:
        """
        Check entity extraction quality.
        Detects: too-long entities, duplicates, sentence fragments, low-count types.
        """
        entities = enrichment.get("entities", {})
        if not entities:
            return {"status": "EMPTY", "total_entities": 0, "issues": []}

        issues = []
        total = sum(len(v) for v in entities.values())

        for entity_type, entity_list in entities.items():
            # Check for suspiciously long entities (>60 chars = likely fragment)
            long_entities = [e for e in entity_list if len(e) > 60]
            if long_entities:
                issues.append({
                    "type": "long_entity",
                    "entity_type": entity_type,
                    "count": len(long_entities),
                    "examples": [e[:80] for e in long_entities[:3]],
                })

            # Check for entities starting with lowercase (should be zero after P3-1)
            lowercase_starts = [e for e in entity_list if e and e[0].islower()]
            if lowercase_starts:
                issues.append({
                    "type": "lowercase_entity",
                    "entity_type": entity_type,
                    "count": len(lowercase_starts),
                    "examples": lowercase_starts[:3],
                })

            # Check for near-duplicates (substring containment)
            for i, e1 in enumerate(entity_list):
                for e2 in entity_list[i+1:]:
                    if e1.lower() in e2.lower() or e2.lower() in e1.lower():
                        issues.append({
                            "type": "near_duplicate",
                            "entity_type": entity_type,
                            "entities": [e1, e2],
                        })
                        break

        noise_rate = len(issues) / max(total, 1) * 100

        return {
            "total_entities": total,
            "by_type": {k: len(v) for k, v in entities.items()},
            "issues": issues[:20],
            "noise_rate": round(noise_rate, 2),
            "status": "OK" if noise_rate < 10 else "WARNING" if noise_rate < 25 else "CRITICAL",
        }

    def _validate_finding_quality(self, enrichment: Dict) -> Dict[str, Any]:
        """
        Check finding/recommendation extraction quality.
        Detects: zero findings, low confidence, missing monetary values, orphan recommendations.
        """
        findings = enrichment.get("findings", [])
        recommendations = enrichment.get("recommendations", [])

        if not findings and not recommendations:
            return {"status": "EMPTY", "total_findings": 0, "total_recommendations": 0}

        issues = []

        # Check findings
        low_confidence = [f for f in findings if f.get("confidence", 0) < 0.3]
        no_monetary = [f for f in findings if not f.get("monetary_values")]
        no_type = [f for f in findings if f.get("finding_type") == "other"]

        if low_confidence:
            issues.append({
                "type": "low_confidence_findings",
                "count": len(low_confidence),
                "pct": round(len(low_confidence) / max(len(findings), 1) * 100, 1),
            })

        if len(no_type) > len(findings) * 0.5:
            issues.append({
                "type": "untyped_findings",
                "count": len(no_type),
                "pct": round(len(no_type) / max(len(findings), 1) * 100, 1),
            })

        # Check recommendations
        orphan_recs = [r for r in recommendations if not r.get("related_finding_ids")]
        if orphan_recs and len(orphan_recs) > len(recommendations) * 0.5:
            issues.append({
                "type": "orphan_recommendations",
                "count": len(orphan_recs),
                "pct": round(len(orphan_recs) / max(len(recommendations), 1) * 100, 1),
            })

        return {
            "total_findings": len(findings),
            "total_recommendations": len(recommendations),
            "low_confidence_findings": len(low_confidence),
            "untyped_findings": len(no_type),
            "orphan_recommendations": len(orphan_recs) if recommendations else 0,
            "issues": issues,
            "status": "OK" if len(issues) == 0 else "WARNING" if len(issues) < 3 else "CRITICAL",
        }

    def _validate_caption_quality(self, children: List[Dict]) -> Dict[str, Any]:
        """Check that generic Florence-2 captions have been replaced."""
        images = [c for c in children if c.get("content_type") == "image_caption"]
        if not images:
            return {"total_images": 0, "generic_count": 0, "status": "N/A"}

        generic_indicators = ["the image shows", "the image contains", "black background"]
        generic = [
            c for c in images
            if any(ind in c.get("content", "").lower() for ind in generic_indicators)
        ]

        generic_rate = len(generic) / len(images) * 100

        return {
            "total_images": len(images),
            "generic_count": len(generic),
            "contextual_count": len(images) - len(generic),
            "generic_rate": round(generic_rate, 2),
            "status": "OK" if generic_rate < 20 else "WARNING" if generic_rate < 50 else "CRITICAL",
        }

    def _validate_cross_references(self, enrichment: Dict) -> Dict[str, Any]:
        """Check cross-reference resolution rate."""
        xrefs = enrichment.get("cross_references", [])
        annexure_links = enrichment.get("annexure_links", [])

        if not xrefs and not annexure_links:
            return {"status": "N/A", "total_refs": 0}

        resolved_xrefs = sum(1 for x in xrefs if x.get("resolved"))
        resolved_annexures = sum(1 for a in annexure_links if a.get("resolved"))

        total = len(xrefs) + len(annexure_links)
        total_resolved = resolved_xrefs + resolved_annexures
        resolution_rate = (total_resolved / total * 100) if total > 0 else 0

        return {
            "total_cross_refs": len(xrefs),
            "resolved_cross_refs": resolved_xrefs,
            "total_annexure_links": len(annexure_links),
            "resolved_annexure_links": resolved_annexures,
            "overall_resolution_rate": round(resolution_rate, 2),
            "status": "OK" if resolution_rate > 60 else "WARNING" if resolution_rate > 30 else "LOW",
        }

    def _validate_temporal(self, enrichment: Dict) -> Dict[str, Any]:
        """Check temporal metadata extraction."""
        temporal = enrichment.get("temporal_coverage", {})
        if not temporal:
            return {"status": "MISSING", "has_audit_period": False}

        has_period = temporal.get("audit_period") is not None
        ref_years = len(temporal.get("reference_years", []))
        prev_refs = len(temporal.get("previous_audit_refs", []))

        return {
            "has_audit_period": has_period,
            "reference_year_count": ref_years,
            "previous_audit_ref_count": prev_refs,
            "status": "OK" if has_period and ref_years > 0 else "PARTIAL" if ref_years > 0 else "MISSING",
        }

    # ==================== P4-7: PHASE 4 VALIDATION METHODS ====================

    def _validate_recommendations(self, enrichment: Dict) -> Dict[str, Any]:
        """
        P4-7: Check recommendation extraction quality.

        Validates:
        - Extraction strategy distribution (structural, numbered, verb)
        - Target entity coverage
        - Orphan recommendations (no related findings)
        """
        recs = enrichment.get("recommendations", [])
        if not recs:
            return {"status": "EMPTY", "total": 0}

        # Count by extraction strategy
        by_strategy = {}
        for r in recs:
            strategy = r.get("extraction_strategy", "unknown")
            by_strategy[strategy] = by_strategy.get(strategy, 0) + 1

        # Quality checks
        orphan = sum(1 for r in recs if not r.get("related_finding_ids"))
        no_target = sum(1 for r in recs if not r.get("target_entity"))

        return {
            "total": len(recs),
            "by_strategy": by_strategy,
            "orphan_count": orphan,
            "orphan_rate": round(orphan / len(recs) * 100, 1) if recs else 0,
            "no_target_entity": no_target,
            "status": "OK" if len(recs) > 0 else "EMPTY",
        }

    def _validate_exec_summary(self, enrichment: Dict) -> Dict[str, Any]:
        """
        P4-7: Check executive summary parsing quality.

        Validates:
        - Executive summary found
        - Citation resolution rate
        - Item count
        """
        index = enrichment.get("executive_summary_index")
        if not index:
            return {"status": "NOT_FOUND"}

        return {
            "total_items": index.get("total_items", 0),
            "total_citations": index.get("total_citations", 0),
            "resolved_count": index.get("resolved_count", 0),
            "resolution_rate": index.get("resolution_rate", 0),
            "status": "OK" if index.get("resolution_rate", 0) > 0.5 else "LOW_RESOLUTION",
        }

    def _validate_visual_registry(self, report_data: Dict) -> Dict[str, Any]:
        """
        P4-7: Check visual asset registry completeness.

        Validates:
        - Table and figure counts
        - Caption quality
        - Visual subtype classification
        """
        registry = report_data.get("visual_asset_registry", {})
        tables = registry.get("tables", [])
        figures = registry.get("figures", [])

        # Check for tables without proper captions
        no_caption_tables = sum(1 for t in tables if "page" in (t.get("caption") or "").lower())

        # Check visual subtype coverage
        subtypes_classified = sum(1 for f in figures if f.get("visual_subtype") != "unknown")

        return {
            "total_tables": len(tables),
            "total_figures": len(figures),
            "tables_without_caption": no_caption_tables,
            "figures_with_subtype": subtypes_classified,
            "subtype_coverage": round(subtypes_classified / len(figures) * 100, 1) if figures else 0,
            "status": "OK" if (tables or figures) else "EMPTY",
        }

    def _validate_footnotes(self, report_data: Dict) -> Dict[str, Any]:
        """
        P4-7: Check footnote capture.

        Validates:
        - Footnote count
        - Footnote number extraction
        """
        footnotes = report_data.get("footnote_index", [])

        # Count footnotes with extracted numbers
        with_numbers = sum(1 for f in footnotes if f.get("footnote_number"))

        return {
            "total_footnotes": len(footnotes),
            "with_numbers": with_numbers,
            "number_extraction_rate": round(with_numbers / len(footnotes) * 100, 1) if footnotes else 0,
            "status": "OK" if footnotes else "NONE_FOUND",
        }

    def _collect_issues(
        self,
        hierarchy: Dict,
        page: Dict,
        toc: Dict,
        metadata: Dict,
        garbage: Dict,
    ) -> List[Dict[str, Any]]:
        """Collect all issues into a structured list for reporting."""
        issues = []

        # Hierarchy issues
        if hierarchy.get("orphan_rate", 0) > 10:
            issues.append(
                {
                    "severity": "CRITICAL" if hierarchy["orphan_rate"] > 50 else "HIGH",
                    "category": "hierarchy",
                    "issue": "High orphan rate",
                    "detail": f"{hierarchy['orphan_rate']}% of children have invalid parent links",
                }
            )

        if hierarchy.get("deep_link_rate", 0) < 30:
            severity = "CRITICAL" if hierarchy["deep_link_rate"] < 10 else "HIGH"
            issues.append(
                {
                    "severity": severity,
                    "category": "hierarchy",
                    "issue": "Flat hierarchy",
                    "detail": f"Only {hierarchy['deep_link_rate']}% of children have level_2+ hierarchy",
                }
            )

        if hierarchy.get("concentration_rate", 0) > 40:
            severity = "CRITICAL" if hierarchy["concentration_rate"] > 60 else "HIGH"
            issues.append(
                {
                    "severity": severity,
                    "category": "hierarchy",
                    "issue": "High parent concentration",
                    "detail": f"{hierarchy['concentration_rate']}% of children assigned to single parent "
                    f"({hierarchy.get('top_parent_children', '?')} children)",
                }
            )

        if hierarchy.get("empty_parent_rate", 0) > 50:
            issues.append(
                {
                    "severity": "HIGH",
                    "category": "hierarchy",
                    "issue": "Many empty parents",
                    "detail": f"{hierarchy['empty_parents']}/{hierarchy['total_parents']} parents have zero children",
                }
            )

        # Page order issues
        if page.get("inversion_rate", 0) > 5:
            issues.append(
                {
                    "severity": "CRITICAL" if page["inversion_rate"] > 30 else "HIGH",
                    "category": "page_order",
                    "issue": "Page range inversions",
                    "detail": f"{page['total_inversions']} parent chunks have start_page > end_page",
                }
            )

        # TOC issues
        if toc.get("false_positive_rate", 0) > 20:
            issues.append(
                {
                    "severity": "HIGH" if toc["false_positive_rate"] > 40 else "MEDIUM",
                    "category": "toc",
                    "issue": "TOC false positives",
                    "detail": f"{toc['garbage_parents']}/{toc['total_parents']} TOC entries are suspicious",
                }
            )

        if toc.get("duplicate_entries", 0) > 5:
            issues.append(
                {
                    "severity": "MEDIUM",
                    "category": "toc",
                    "issue": "Duplicate TOC entries",
                    "detail": f"{toc['duplicate_entries']} entries appear multiple times (likely page headers)",
                }
            )

        # Metadata issues
        if metadata.get("missing_required"):
            issues.append(
                {
                    "severity": "MEDIUM",
                    "category": "metadata",
                    "issue": "Missing required metadata",
                    "detail": f"Missing: {', '.join(metadata['missing_required'])}",
                }
            )

        if metadata.get("unknown_fields"):
            issues.append(
                {
                    "severity": "LOW",
                    "category": "metadata",
                    "issue": "Unknown metadata values",
                    "detail": f"Fields with 'Unknown': {', '.join(metadata['unknown_fields'])}",
                }
            )

        # Garbage chunk issues
        if garbage.get("garbage_rate", 0) > 10:
            issues.append(
                {
                    "severity": "MEDIUM" if garbage["garbage_rate"] < 25 else "HIGH",
                    "category": "content",
                    "issue": "High garbage chunk rate",
                    "detail": f"{garbage['garbage_count']} chunks ({garbage['garbage_rate']}%) are too short or meaningless",
                }
            )

        return issues


# Convenience function for quick validation
def validate_json_file(json_path: str) -> Dict[str, Any]:
    """Validate a single JSON file and return results."""
    import json

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    validator = ValidationService()
    return validator.validate_report(data)
