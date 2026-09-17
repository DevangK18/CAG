# CAG Parsing Pipeline: Old vs New Comparison Report

**Date:** February 15, 2026
**Reports Analyzed:**
1. **Bharatmala** — `2023_19_CAG_Performance_Audit_of_Implementation_of_PhaseI_of_Bharatmala_Pariyojana` (Performance Audit, 264 pages)
2. **Direct Tax** — `2025_14_Compliance_Audit_on_Direct_taxes_for_period_202223_for_the_Union_Government_Depa` (Compliance Audit, 131 pages)

**Old Pipeline:** Baseline (pre-Phase 1), processed Dec 31, 2025
**New Pipeline:** Post Phase 1–4, processed Feb 15, 2026

---

## 1. Executive Summary

The new pipeline introduces significant new capabilities (cross-references, temporal metadata, visual registry, executive summary parsing, entity hardening) and improves finding/recommendation extraction. However, it introduces a **critical hierarchy regression** in both reports — hierarchy depth collapsed from 3–4 levels to 1–2 levels, and the Bharatmala report suffers near-total hierarchy failure (99.5% of chunks assigned to a single parent). This regression will severely impact RAG retrieval precision until fixed.

### Scorecard At-a-Glance

| Dimension | Bharatmala | Direct Tax |
|-----------|:----------:|:----------:|
| Hierarchy Quality | 🔴 Major Regression | 🟡 Regression |
| Finding Extraction | 🟢 Improved (26→92) | 🟢 Improved (62→92) |
| Recommendation Extraction | 🟡 Over-extraction (14→148) | 🟢 Improved (12→56) |
| Entity Quality | 🟢 Much cleaner | 🟢 Much cleaner |
| New Features | 🟢 All populated | 🟢 Mostly populated |
| RAG Readiness (overall) | 🔴 Degraded | 🟡 Mixed |

---

## 2. Structural Comparison

### 2.1 Chunk Counts

| Metric | Bharatmala OLD | Bharatmala NEW | Direct Tax OLD | Direct Tax NEW |
|--------|:-:|:-:|:-:|:-:|
| Parent chunks | 237 | 471 (+234) | 243 | 300 (+57) |
| Child chunks | 1,790 | 1,778 (−12) | 748 | 746 (−2) |
| Paragraphs | 1,399 | 1,390 | 554 | 553 |
| Tables | 104 | 100 | 62 | 61 |
| Headers | 265 | 266 | 113 | 113 |
| Images | 22 | 22 | 19 | 19 |

**Observation:** Child chunk counts are nearly identical, confirming that the core extraction/filtering pipeline is stable. Parent chunks increased significantly — the new pipeline generates more parent-level scaffolding. However, the parent chunk records themselves are empty shells in both old and new (no title, level, or page range populated in the parent_chunks array), meaning all hierarchy information lives in child chunk `hierarchy` fields.

### 2.2 Hierarchy Quality — 🔴 Critical Regression

This is the most consequential change between old and new pipelines.

#### Bharatmala — Hierarchy Collapsed

| Metric | OLD | NEW |
|--------|-----|-----|
| Unique hierarchy assignments | 236 | **2** |
| Hierarchy levels used | level_1 through level_4 | level_1 and level_2 only |
| Max single-parent concentration | 5.6% | **99.5%** |
| Depth distribution | L1: 119, L2: 388, L3: 954, L4: 329 | **L2: 1,778 (100%)** |

**What happened:** In the OLD pipeline, chunks were assigned across 236 unique hierarchy paths with good depth (most chunks at L3/L4). The level_1 had a known issue (95.5% of chunks under "EXECUTIVE SUMMARY"), but level_2 through level_4 provided granular section breakdown (e.g., "5.2.1 Lane specifications for BPP-I", "7.2.1 Project Monitoring Information System").

In the NEW pipeline, **all 1,778 chunks** collapsed into just 2 hierarchy values:
- 1,769 chunks (99.5%): `{level_1: "Preface", level_2: "Annexures"}`
- 9 chunks (0.5%): `{level_1: "Preface", level_2: "Executive Summary"}`

This is a catastrophic regression for RAG — every query retrieves from a single undifferentiated pool with no section-level filtering capability.

#### Direct Tax — Hierarchy Flattened

| Metric | OLD | NEW |
|--------|-----|-----|
| Unique hierarchy assignments | 205 | 33 |
| Hierarchy levels used | level_1 through level_4 | **level_1 only** |
| Max single-parent concentration | 3.3% | 18.4% |
| Depth distribution | L1: 107, L2: 77, L3: 546, L4: 18 | **L1: 746 (100%)** |

**What happened:** The old pipeline had 205 unique section paths with depth up to L4. The new pipeline flattened everything to level_1 only. The section names at level_1 are reasonable (e.g., "4.3 Administration of tax concessions/exemptions/deductions", "1.3 Resources of the Union Government"), but all sub-section granularity is lost.

The concentration is less severe than Bharatmala (max 18.4% vs 99.5%), but the loss of depth means a query like "What were the irregularities in allowing depreciation?" cannot filter to section 3.3.2 — it must search all of "Chapter III: Corporation Tax".

### 2.3 Top-Level Keys — New Structure

| Key | OLD | NEW |
|-----|:---:|:---:|
| report_metadata | ✅ | ✅ |
| parent_chunks | ✅ | ✅ |
| child_chunks | ✅ | ✅ |
| processing_stats | ✅ | ✅ |
| semantic_enrichment | ✅ | ✅ |
| footnote_index | ❌ | ✅ (Phase 4) |
| visual_asset_registry | ❌ | ✅ (Phase 4) |

---

## 3. Semantic Enrichment Comparison

### 3.1 Findings — 🟢 Improved Coverage

| Metric | Bharatmala OLD | Bharatmala NEW | Direct Tax OLD | Direct Tax NEW |
|--------|:-:|:-:|:-:|:-:|
| Total findings | 26 | **92** (+254%) | 62 | **92** (+48%) |
| With monetary values | 25 | 29 | 62 | **81** |
| loss_of_revenue | 0 | 0 | 44 | 44 |
| non_compliance | 4 | 4 | 3 | 4 |
| other (untyped) | 22 | **88** | 15 | **44** |
| Critical severity | 17 | 18 | 37 | **48** |
| High severity | 7 | 9 | 20 | 24 |
| Low severity | 0 | **62** | 0 | **13** |

**Analysis:** Finding count increased significantly, which is positive — the enhanced semantic patterns (Phase 1 P1-2) and implicit finding detection are catching previously missed findings. However, most new findings are typed as "other" with "low" severity, suggesting the implicit finding detection is working but the type/severity classification needs tuning. The original typed findings (loss_of_revenue, non_compliance) are preserved.

### 3.2 Recommendations — 🟡 Possible Over-Extraction

| Report | OLD | NEW | Change |
|--------|:---:|:---:|:------:|
| Bharatmala | 14 | **148** | +957% |
| Direct Tax | 12 | **56** | +367% |

**Analysis:** The multi-strategy recommendation extraction (Phase 4 P4-3) dramatically increased recall. For Bharatmala, 148 recommendations seems high — the report likely contains around 41 actual recommendations (the exec summary mentions "41 recommendations"). This suggests over-extraction: sentence-level fragments or repeated mentions are being counted as separate recommendations. The new recommendations do have richer finding links (multiple finding IDs per recommendation vs single links in old).

### 3.3 Entity Extraction — 🟢 Much Cleaner

| Category | Bharatmala OLD | Bharatmala NEW | Direct Tax OLD | Direct Tax NEW |
|----------|:-:|:-:|:-:|:-:|
| Schemes | 203 | **53** (−74%) | 74 | **51** (−31%) |
| Ministries | 15 | **14** (−7%) | 5 | **5** (0%) |
| Organizations | 138 | **21** (−85%) | 46 | **9** (−80%) |

**Quality before (OLD):** Entity lists were heavily polluted with sentence fragments:
- Schemes: `"1971 for submission"`, `"287 km under Bharatmala Pariyojana"`, `"324 crore for such other scheme"`
- Organizations: `"000 crores would be appraised by the Delegated Investment Board"`, `"152 Joint measurement survey carried out by respective Competent Authority"`

**Quality after (NEW):** Entities are dramatically cleaner thanks to P3-1 hardening:
- Schemes: `"Atmanirbhar Bharat Scheme"`, `"Logistics Efficiency Enhancement Program"`, `"Cabinet Committee on Economic Affairs"`
- Organizations: `"Central Vigilance Commission"`, `"Dedicated Freight Corridor Corporation"`, `"Damodar Valley Corporation"`

**Remaining issues:** Some noise persists — e.g., `"Assessing Officer"` and `"Budget Estimates"` appearing as schemes in Direct Tax, and `"Anakapalli"` (a place name) as a scheme in Bharatmala. The uppercase-start requirement and verb rejection filter are working, but keyword-suffix matching still catches false positives.

---

## 4. New Features (Phase 3/4)

### 4.1 Cross-References — 🟢 New Capability

| Metric | Bharatmala | Direct Tax |
|--------|:----------:|:----------:|
| Total cross-references | 86 | 131 |
| Resolved | 38 (44.2%) | 44 (33.6%) |
| Unresolved | 48 | 87 |

Cross-reference types found: chapter references, para references, table references. Resolution works well for chapter-level references but struggles with para and table references. Sample resolved: `"Chapter 1" → parent_L1_1 (page 20)`, `"Chapter IV" → parent_L1_IV (page 90)`.

### 4.2 Annexure Links — 🟢 New (Bharatmala only)

| Metric | Bharatmala | Direct Tax |
|--------|:----------:|:----------:|
| Annexure links | 16 | 0 |
| Resolved | 15 (93.8%) | N/A |

Excellent resolution rate. Annexure references in paragraph text are correctly linked to the Annexures parent chunk. Direct Tax report doesn't use annexure references in the same way.

### 4.3 Temporal Coverage — 🟢 New Capability

| Metric | Bharatmala | Direct Tax |
|--------|:----------:|:----------:|
| Audit period detected | ✅ (2017–2020) | ❌ (None) |
| Reference years | 24 years extracted | 21 years extracted |
| Previous audit refs | 3 | 3 |

Bharatmala's audit period extraction is correct. Direct Tax audit period was not detected (the report covers FY 2022-23, which should have been extractable from the title). The reference year extraction is noisy — some years (2024, 2025, 2027 for Bharatmala) are likely false positives from page numbers or reference numbers, not actual fiscal years.

### 4.4 Executive Summary Index — 🟡 Partial

| Metric | Bharatmala | Direct Tax |
|--------|:----------:|:----------:|
| Detected | ✅ | ❌ |
| Total items | 25 | — |
| Citations resolved | 0 (0.0%) | — |

The executive summary was detected for Bharatmala but citation resolution completely failed (0%). This means the paragraph references inside the exec summary (e.g., "(Paragraph 3.1)") were not matched to actual chunks — likely related to the hierarchy collapse making chunk identification impossible.

### 4.5 Visual Asset Registry — 🟢 New Capability

| Metric | Bharatmala | Direct Tax |
|--------|:----------:|:----------:|
| Tables registered | 100 | 61 |
| Figures registered | 22 | 19 |

Both reports now have a centralized registry of all visual assets with metadata. This enables table/figure navigation in the frontend.

### 4.6 Features Not Triggered

| Feature | Bharatmala | Direct Tax | Note |
|---------|:----------:|:----------:|------|
| Footnotes | 0 | 0 | Neither report has Docling-labeled Footnote blocks |
| Box elements | 0 | 0 | Neither report uses "Box X.X" pattern |
| Structured table data | 0 | 0 | `structured_data` field empty on all chunks |

**Note on structured_data:** Despite Phase 1 P0-1 targeting structured table extraction, no chunks in either report have the `structured_data` field populated. Tables remain as opaque markdown strings. This is either a bug in the pipeline integration or the structured extractor was implemented but not wired into the assembly output.

---

## 5. Regression Analysis

### 5.1 Hierarchy — Root Cause Hypothesis

The Phase 1 P0-2 Y-coordinate hierarchy fix was designed to solve the 92.3% concentration problem by using vertical position for section assignment. Instead, it appears to have **broken the hierarchy builder entirely**:

- Parent chunks increased in count but are all empty shells (no level, title, or page range)
- Child hierarchy depth collapsed: Bharatmala went from 4 levels to 2, Direct Tax from 4 to 1
- Bharatmala's scaffolding appears to have failed to detect any TOC structure beyond "Preface", resulting in everything falling into "Annexures" (the last major section detected)

The old pipeline had its own hierarchy issues (e.g., 95.5% of Bharatmala at level_1 = "EXECUTIVE SUMMARY"), but it compensated with deep sub-section assignment at levels 2–4. The new pipeline lost this depth entirely.

### 5.2 Impact on RAG

| Capability | OLD (working) | NEW (broken) |
|-----------|:---:|:---:|
| "Show me findings from Chapter 3" | ✅ Could filter by level_1/level_2 | 🔴 All chunks under "Annexures" |
| "What about section 5.2.1?" | ✅ Level_3 = "5.2.1 Lane specifications" | 🔴 No level_3 exists |
| Retrieve with section context | ✅ Inherited hierarchy chain | 🔴 Meaningless hierarchy |
| Section-scoped summarization | ✅ Parent chunks had page ranges | 🔴 No page ranges |

---

## 6. Summary: What Improved, What Regressed

### ✅ Improvements

1. **Entity extraction** is dramatically cleaner (−74% to −85% noise reduction)
2. **Finding count** nearly doubled for Direct Tax, tripled for Bharatmala
3. **Cross-reference resolution** is a new capability (86–131 refs detected per report, 33–44% resolved)
4. **Annexure linking** works excellently where applicable (93.8% resolution)
5. **Temporal metadata** extraction is new and mostly functional
6. **Visual asset registry** provides structured table/figure listings
7. **Recommendation extraction** has much higher recall with richer finding links

### 🔴 Regressions

1. **Hierarchy depth** collapsed from 4 levels to 1–2 levels in both reports
2. **Bharatmala hierarchy** is catastrophically broken (99.5% concentration)
3. **Parent chunk records** are empty (no title, level, page ranges)
4. **Executive summary** citation resolution is 0% (likely caused by hierarchy failure)
5. **Structured table data** is not populated despite being a Phase 1 target
6. **Recommendation over-extraction** (148 for a report with ~41 actual recommendations)
7. **Finding type classification** is weak (88/92 = "other" for Bharatmala)

### 🟡 Neutral / Mixed

1. Child chunk counts stable (no content loss)
2. Processing errors unchanged (10 for Bharatmala, 8 for Direct Tax)
3. Temporal coverage has some false positive years
4. Footnote and box detection found nothing (may be correct if reports lack these elements)

---

## 7. Recommended Priority Fixes

1. **P0 — Fix hierarchy builder.** The scaffolding/chunking service changes from Phase 1 P0-2 broke hierarchy assignment. Restore depth and verify concentration stays below 15%.
2. **P0 — Wire structured_data into assembly.** Phase 1 P0-1 structured table extraction is not appearing in output JSON.
3. **P1 — Tune recommendation deduplication.** Add dedup/merge logic to prevent 148 recommendations from a 41-recommendation report.
4. **P1 — Improve finding type classification.** Too many findings classified as "other" — the report-type profiles and pattern matching need refinement.
5. **P2 — Fix temporal year extraction.** Filter out years from page numbers, reference numbers, and future dates.
6. **P2 — Fix executive summary citation resolution.** Likely depends on hierarchy fix.
