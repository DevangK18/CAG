# CAG Parsing Pipeline — Comprehensive Cross-Report Analysis

**Corpus:** 8 stress-profile reports across all three tiers. **Method:** evidence-anchored aggregation of per-report investigations, each of which triangulated trace ↔ JSON ↔ source PDF. Every finding below is backed by ≥1 concrete pointer (trace § / json path / pdf page) from a per-report doc; widespread findings carry a count of reports affected.

---

## 0. Executive Summary

**Eight reports analyzed, zero clean baselines.** Even reports designed as healthy baselines (`2023_7 NHAI Toll`, score 95/100 per pre-trace diagnostics; `OD_2025_05 School Education`, clean state high-scorer) came back as CONCERN with 4–5 Class-A silent failures each. Final scorecard: 0 GOOD, 7 CONCERN, 1 DEGRADED. The pre-trace diagnostic score (a structural-completeness proxy) is not predicting parse quality — it's predicting how cleanly the *current* gates fire, which is a different thing entirely. Diagnostics gave NHAI and OD high marks; ground-truth analysis exposed that both ship significant semantic damage that no current red flag catches.

**40+ distinct Class-A silent failures discovered across the corpus.** A "Class-A silent failure" is the worst category: output is wrong/incomplete and *no red flag fired*. These are not edge cases — they are systemic and concentrated in four code regions.

**The four issues that demand immediate attention, ranked by combined impact × reach:**

1. **Monetary extraction is broken in 7 distinct ways across 8/8 reports.** The most severe: total inflation by 2×–100,000× depending on the bug. ₹318,109 crore reported for a Bihar local-body report (impossible — exceeds India's GDP); ₹322 lakh crore reported for a Union financial audit (12× India's GDP); every Union finding `monetary_value=None` despite explicit "₹49,942 crore" in text. **No sanity-check red flag exists** for impossible totals, so the pipeline silently emits these numbers.

2. **The 'other' finding-type bucket is overfull across 8/8 reports.** Range 34%–87% (mean ~58%; threshold is 30%). The red flag fires correctly but the underlying typology is structurally incomplete: it lacks types this corpus's text demands, and it doesn't fire on the dominant linguistic pattern in CAG reports ("Audit observed/noticed/compared that..."). The 'other' bucket also holds ~87% of total monetary value in some reports — so the broken monetary extractor compounds with broken classification.

3. **Phase 5.5 TOC reconciliation simultaneously rescues and pollutes across 8/8 reports.** When it works (quality 0→100 in 4 reports, 64→98 / 70→100 in 3 more), it injects file-assembly artifact names, garbled OCR titles, page-header text, parenthetical paragraph citations, duplicate section-numbered headings, and sub-paragraph items promoted to Level 1. It has no output validation/sanitization pass. In `BR_2024_3` the quality-tier comparison logic itself is logically inverted (`70 < 40` evaluates as true and routes to low tier).

4. **Trace ↔ JSON provenance is unverified across 4/8 reports.** The trace was generated from a newer code version than the JSON it claims to narrate. Detectable signs: `report_id` zero-padding inconsistency (`2025_4` vs `2025_04`; `BR_2024_03` vs `BR_2024_3`), assembly_timestamp ≠ trace timestamp, count divergence (parents/findings/tables/figures/monetary all off). This is both an *analysis* problem (trace ↔ JSON comparisons may be invalid) and a *real* pipeline bug (report_id generation isn't deterministic).

Below: cross-report metrics table, then the full pattern catalog with action priorities.

---

## 1. Cross-Report Scorecard

| Report | Tier | Pages | Verdict | toc_q before→after | LLM 5.7 | Tables in JSON | DLQ / lost pages | Parents | unassigned% | concentration% | Findings | 'other'% | Monetary cr (claimed) | Class-A failures |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025_4 Union Fin Audit | union | 134 | DEGRADED | 94→95 | skip✓ | 61 (trace says 77) | 4 pages lost in annexure | 167 (trace 138) | 0% | 3.7% | 30 (trace 36) | 86.7% | 2,871,672 (impossible) | **11** |
| 2023_20 Food_grains | union | 146 | CONCERN/BUG | 0→100 | skip (fab) | 80 | 4 pages lost (§5.4) | 163 | 0% | 3.3% | 71 | 60.6% | 12,622 (~2× inflated) | 2+3 |
| 2023_7 NHAI Toll | union | 108 | CONCERN | 0→98 | skip✓ | 42 | 0 logged | 103 | 0% | 3.8% | 50 | 34.0% | 12,428 | **5** |
| GJ_2024_03 NSAP/DBT | state | 56 | CONCERN | 0→100 | skip (fab) | 22 | 0 | 52 | 0% | 11.4% | 15 | 53.3% | 660 (with 846× & 40× errors) | 5 |
| UK_2025_06 MGNREGA | state | 160 | CONCERN | 64→98 | skip✓ | 70 | 3 pages lost (Appendix-5.7) | 167 | 0% | 3.0% | 46 | 54.3% | 370 (clean) | 4 |
| OD_2025_05 School Edu | state | 178 | CONCERN | 0→99 | skip (fab) | 92 | ~8 rotated tables lost | 174 | 0% | 3.8% | 116 | 56.9% | 7,457 (~50% inflated) | **5** |
| CG_2025_1 Chhattisgarh | local | 129 | CONCERN | 0→0 | fire→0-effect | 45 | 0 logged | 132 | 0% | 3.4% | 60 | 70.0% | 68 | 3 |
| BR_2024_3 Bihar | local | 226 | CONCERN | 70→100 | skip✓ | 97 | 0 logged | 256 | 0% | 5.5% | 117 | 42.7% | 318,109 (physically impossible) | **5** |

**Reading the table:**
- **"toc_q before→after"** showing **0→100** (Food_grains, GJ, OD): Phase 5.5 inflates a quality-zero scaffold to a perfect score, suppressing Phase 5.7 LLM validation. The recovery is real but the score is fabricated. "skip (fab)" in the LLM column flags this.
- **Concentration column** is universally healthy (3.0%–5.5% with one 11.4% outlier). Phase 7.5 skips correctly every time — but this metric only catches *one* hierarchy failure mode, not the half-dozen others observed.
- **Unassigned %** is **0% in all 8 reports**. Phase 7 child-to-parent assignment is one of the strongest parts of the pipeline.
- **"DLQ / lost pages"** column: silent data loss confirmed in 3 of 8 (Union, Food_grains, UK). The pipeline reports 0 DLQ in every case — yet pages 111, 114, 115, 118 of the Union annexure, pages 121, 124, 125, 126 of the Food_grains compliance review, and pages 140, 144, 145 of the UK appendix are completely absent from JSON. No flag fires.

---

## 2. Universal Pattern Catalog — Issues Affecting 6/8+ Reports

### 2.1 Monetary extraction is broken in seven distinct ways

**Reach: 8/8 reports. Severity: P0.** This is the single largest cluster of bugs and the one that most affects downstream usability — the headline number in every report is wrong.

The seven failure modes, with evidence:

**(A) Per-finding `monetary_value` (singular) field is empty everywhere.**
- `2025_4 Union` (F01 P0): all 30 findings have `monetary_value: None` despite explicit "₹2,41,220.26 crore" (pdf p.55) and "₹49,942 crore" (pdf p.48) in finding descriptions.
- `UK_2025_06` (F03 P0): all 46 findings have `monetary_value=None` while the plural `monetary_values` array IS populated. Naming inconsistency — downstream consumers expecting the singular field get nothing.
- Likely affects all 8; only spot-checked in 3.

**(B) Same amount double-counted: "₹X crore" + bare "X crore" matched twice.**
- `2023_20 Food_grains` (F02 P0): finding_001 has ₹62.76 crore appearing twice in `monetary_values` ("₹ 62.76 crore" + "62.76 crore"); 45 of 71 findings exhibit this. Total inflated ≈2× (₹12,622 → ≈₹6,300 crore).
- `OD_2025_05` (F02 P0): finding on p.34 has duplicate raw_texts "₹1,141.22 crore" + "1,141.22 crore"; total ₹7,457 cr inflated ~40–50%.
- `BR_2024_3` (F01 P0): finding_009 has 5 entries for 2 unique amounts. Total ₹318,109 crore — physically impossible for a local-body audit.

**(C) Per-unit × beneficiary aggregation produces wrong totals.**
- `GJ_2024_03` (F03 P0): Finding 4 says ₹46,980 crore where PDF p.37 explicitly states ₹55.60 crore (₹20,000 × 27,801 beneficiaries) — **846× off**. Finding 14 says ₹54.18 crore where PDF p.39 states ₹1.35 crore (= ₹135.46 lakh) — **40× off**. Per-unit amount being multiplied as if it were the total.

**(D) Indian comma-grouping not handled.**
- `2025_4 Union` (F01 P0): "₹2,41,220.26 crore" (Indian lakh-style grouping) not parsed correctly. Regex appears written for Western "₹241,220.26" form.

**(E) Year-like patterns parsed as currency.**
- `BR_2024_3` (F01 P0): "rs 2003" (from a year reference "2003-04") parsed as ₹2,003.

**(F) Aggregate `monetary_aggregates` field empty despite per-type stats populated.**
- `2023_7 NHAI Toll` (F02 P0): `json: semantic_enrichment.monetary_aggregates = {}` while `statistics.findings.total_monetary_crore = 12,428.57`.
- `OD_2025_05` (F06 P1): same pattern — `monetary_aggregates: {}` while statistics is populated.
- `2025_4 Union`: same — `tables_by_section: {}, figures_by_section: []` empty despite totals.
- `2023_20 Food_grains` (F11 P2): same — `monetary_aggregates={}` (spec field unpopulated; data lives under `statistics.findings.by_type`).

**(G) Two independent aggregation paths produce inconsistent totals.**
- `2025_4 Union`: trace reports `monetary_crore: 32,191,934.97` while JSON reports `total_monetary_crore: 2,871,672.58`. Both implausibly large (322 lakh crore = 12× India's GDP; 2.87 lakh crore = comparable to India's defense budget for an audit report covering specific reserve funds). Third path: per-finding sum = 0 (because all `monetary_value` are None). Three values, no two agree.

**(H) No sanity check / red flag for impossible totals.**
- All 8 reports. `BR_2024_3` reports ₹318,109 crore for a local body. `2025_4 Union` reports ₹322 lakh crore. No gate flags impossibly large monetary aggregates given tier or report context.

**Downstream consequence beyond the headline number:** in `2023_20 Food_grains`, the double-counting flips at least 3 findings from HIGH severity to false CRITICAL (deduped amounts ₹62.76 / ₹71.85 / ₹76.74 cr would land in the HIGH band, but the inflated doubles push them past the critical threshold). The severity tiering (Union ≥₹100 cr, State ≥₹50 cr, Local ≥₹10 cr) is correctly applied — but applied to wrong inputs.

**Code locations referenced in per-report docs:**
- `monetary_processor` (Union F01) — needs Indian comma-grouping support, needs to be called on `finding.description`
- Finding extractor for source_chunk → monetary linkage
- Assembly step for `monetary_aggregates` and visual_asset_registry `*_by_section` population

### 2.2 The 'other' finding-type bucket is overfull

**Reach: 8/8 reports.** All exceed the 30% red-flag threshold; range 34%–87%; mean ≈58%. **Severity: P0** because (a) the typology gap silently degrades every report's primary analytical output, and (b) the bucket holds ~87% of monetary value in `2023_20 Food_grains` — so the broken monetary extractor compounds with broken classification.

The red flag fires correctly in 7 of 8 (the 8th, `CG_2025_1`, had a trace from a degraded run with 0 findings so it couldn't fire). Class B true positive every time — *but* the deeper issue is Class A: the typology is **structurally unable** to label the audit observations this corpus contains.

**Three distinct failure modes:**

**(A) Tier-specific taxonomy gaps.**
- `2025_4 Union` (Check 5): Union profile lacks `accounting_irregularity`, `non_realization_of_dues`, `system_deficiency` — types that the State/Local profiles have. Union Financial Audit findings about misclassification of capital expenditure (pdf p.48, ₹49,942 crore), short-transfer to Reserve Funds (pdf p.55, ₹2,41,220.26 crore collected vs ₹344.48 crore transferred), unrealized dividend (pdf p.56), and dormant accounts (pdf p.51) cannot be properly typed. ~20 of 26 'other' findings would be typed if these types were available.

**(B) Audit-observation linguistic patterns not matched.**
- Confirmed across `OD_2025_05` (Check 5), `UK_2025_06` (Check 5), `CG_2025_1` (Check 5), `2023_20 Food_grains` (Check 5), `2023_7 NHAI Toll` (Check 5), `BR_2024_3` (Check 5), `GJ_2024_03` (Check 5). The classifier doesn't fire on:
  - **"Audit observed/noticed/compared that..."** + deficiency keywords (the dominant CAG narrative pattern)
  - **"was not maintained / not done / not adhered to / not prepared"** without monetary amounts → `non_compliance`
  - **"X% vs required Y%"** / **"target vs actual shortfall"** → `performance_shortfall`
  - **"transferred as loan from [scheme A] to [scheme B]"** / **"utilized for inadmissible items"** → `diversion_of_fund` / `irregular_expenditure`
  - **"no [committee/facility/policy/mechanism] in any [test-checked entity]"** → `system_deficiency`
  - **"UC non-submission"** / **"unreconciled accounts"** → `non_compliance` / `fund_utilization_failure`
  - **"₹X collected vs ₹Y expenses"** revenue-cost gap → `loss_of_revenue`
  - **"extra/avoidable expenditure of ₹X due to delay"** → `wasteful_expenditure`
  - **"unutilised / idle land / assets"** → `idle_assets`
  - **Regulatory-context leads** ("NH Fee Rules", "MoRTH notified", "NSAP Guidelines mandate") before describing the non-compliance (most common in `2023_7 NHAI Toll`)

**(C) Non-findings extracted as findings (false positives polluting the bucket).**
- `GJ_2024_03` (F05 P1): Finding 6 is the "Brief Snapshot" summary block from pdf p.30. This is a chapter-opening summary box, not an audit observation. Pattern: "Brief Snapshot" boxes appear at the start of every chapter in CAG reports.
- `2023_20 Food_grains` (Check 5): "10 Depot months denotes number of months a depot was hired…" — a footnote/definition leaked in.
- `BR_2024_3` (Check 5): finding_007 (p.24) "Departments of GoB transferred functions to PRIs..." — contextual/historical background, not a finding. Pattern: `audit_revealed` pattern is too broad — it matches the phrase "Audit observed that" wherever it appears, including in narrative context.
- `UK_2025_06` (Check 5): Findings 9 and 10 are preamble paragraphs ("Shortcomings in registration and employment generation", "Work files found deficient") — not specific observations.

**Compounding effect:** in `2023_20 Food_grains`, the 'other' bucket holds ₹10,975 crore of the ₹12,622 crore total monetary value (87%) — meaning the broken classifier dumps almost all monetary analysis into the un-typed bucket.

### 2.3 Phase 5.5 TOC reconciliation rescues and pollutes simultaneously

**Reach: 8/8 reports.** Phase 5.5 is the single most consequential phase in the pipeline — it produces the hierarchy backbone every downstream phase depends on. **Severity: P0** for the noise injection (it propagates into every later phase) and **P0** for the inverted-comparison bug in `BR_2024_3`.

**The rescue (genuinely impressive):**
| Report | toc_q before → after | Method |
|---|---|---|
| 2023_7 NHAI Toll | 0 → 98 | merged 105 Docling headers |
| 2023_20 Food_grains | 0 → 100 | merged 163 from Docling |
| GJ_2024_03 NSAP | 0 → 100 | merged 61 Docling headers |
| OD_2025_05 School Edu | 0 → 99 | merged 175 Docling headers |
| CG_2025_1 Chhattisgarh | 0 → 0 | failed (scanned, no text) |
| UK_2025_06 MGNREGA | 64 → 98 | merged 171 Docling headers |
| BR_2024_3 Bihar | 70 → 100 | docling_primary override |
| 2025_4 Union | 94 → 95 | supplement (boost 1) |

**The pollution (eight distinct noise types injected):**

**(A) File-assembly artifact names propagated into parent toc_entries.**
- `UK_2025_06` (F05 P1, Check 4): "7_Chapter-2", "9_Chapter-4", "11_Chapter-6", "12_Chapter-7", "13_Chapter-8", "14_Appendices", "15_Separator" persist as parent titles. The finding `chapter` field shows `"15_Separator"`. Assembly-pattern penalty was applied but score 64 still passed the 60 threshold despite 14 "Blank Page" entries and 9 "15_Separator" entries.

**(B) Garbled OCR / encoded-font text promoted to parents.**
- `CG_2025_1` (F06 P1): 5 parents with nonsense titles ("¢-xIpuody", "SIRTS[euoneszsd...") from rotated landscape appendix pages. 71 children assigned beneath them.
- `OD_2025_05` (F07 P1): "of s New sec Add clas Sci" at [158,170] is a corrupted appendix-page artifact promoted to Level 1.
- `2023_7 NHAI Toll` (F06 P1): ROT-3 encoded fonts on pages 0, 70, 85 produce phantom parents with titles like `5HSRUW\x03RI\x03WKH...` and `&KDSWHU\x039\x03$YDLODELOLW\\...`. The "CHAPTER V" parent covers only the separator pages [68,69]; the actual chapter content lives under the garbled parent — they're split into two separate Level-1 parents.
- `GJ_2024_03` (F08 P1): garbled parent entries [0] and [1] from font-encoded page 2 with characters like "ZĞƉŽƌƚ ŽĨ ƚŚĞ...".

**(C) Page-header / running text mis-promoted to sections.**
- `2025_4 Union`: `parents[44]: "Report No. 4 of"` is a page-running header; `parents[50]: "b. Suspense Head - Cheques and Bills"` is a sub-list item.

**(D) Parenthetical paragraph citations promoted to sections.**
- `2023_20 Food_grains` (F06 P2): `parents[6..12]` are exec-summary citation references like "(Paragraph 4.3.3)" treated as section headers. ~8 such noise parents.
- `BR_2024_3` (F04 P1): "(Paragraph 5.2)", "(Source: Records of the test-checked ULBs)" promoted to Level 2 parents.

**(E) Sub-paragraph items promoted to L1.**
- `BR_2024_3` (F04 P1): "(i) Loss of central share..." and "(iv) Non-utilisation of grants..." are L1 parents with page ranges [88, 90] and [90, 124]. They should be L3 children of section 5.3. **The L1 promotion gives them jurisdiction over pages that belong to sections 5.4–5.9, causing widespread mis-parenting of unrelated content.**

**(F) Duplicate parent entries at different levels for the same section.**
- `2023_7 NHAI Toll` (F05 P1): 14 duplicates (e.g., "5.5 Non-Maintenance" at both L2 and L4; 3.1.2 at L3 and L4).
- `2025_4 Union`: 3.5.1, 3.5.2, 3.5.3, 3.5.4 each appear twice as adjacent parents.
- `OD_2025_05` (F08 P1): 6 duplicates ("2.2.4.1", "3.1.2", "3.1.5.1", "4.2.3.2", "5.1", "5.4").
- `GJ_2024_03` (F09 P1): section 3.2 appears as both parent[27] (L1) and parent[28] (L2) with same title.
- `UK_2025_06` (Check 4): "12_Chapter-7" exists alongside the real Chapter 7 parent.

**(G) Hierarchy level gaps.**
- `OD_2025_05` (F09 P1): 9 Level-3 entries have no Level-2 ancestor in their `hierarchy` dict (e.g., "2.1 Deficiencies in Planning" has `{level_1: "Chapter 2…", level_3: "2.1…"}` — no level_2).

**(H) Inverted quality-tier comparison.**
- `BR_2024_3` (F02 P0): trace says `quality_tier: low, Reason: quality_score=70 < medium_threshold=40` — **70 is NOT < 40**. Per `PARSING_CONFIG.md` spec, quality ≥70 should route to "high" tier (preserve Phase 4 TOC as primary). Either the code comparison is inverted, or the trace reason string is wrong. Practical impact on this report was limited because Phase 4 had 0 entries to preserve, but the bug remains: on a report where Phase 4 produces a valid TOC, this would discard it.

**(I) Empty parent stubs created.**
- `2023_20 Food_grains` (Check 5/Section 4): 21 of 163 parents have 0 children — most are noise, but real sections like "1.6 Audit objectives" (pdf p.18) are empty because their content was parented to a neighbour.
- `UK_2025_06` (F09 P2): 33 of 167 parents have 0 children, including "6_Chapter" (artifact) and "3.8 Conclusion" (genuine but very short).

**Root cause:** Phase 5.5 has **no output validation/sanitization pass**. It merges Docling section-headers without filtering candidates that match running-header patterns, parenthetical citation patterns, encoded-font ranges, or assembly artifacts. The quality score it emits (often 100) is fabricated relative to the actual structural fidelity, which suppresses Phase 5.7 LLM rescue.

### 2.4 Trace ↔ JSON provenance is unverified

**Reach: 4/8 reports (and one near-instant re-run).** **Severity: P0** because (a) every cross-artifact comparison in those reports may be invalid, and (b) the underlying cause includes a real pipeline bug.

**Confirmed mismatches:**
- `2025_4 Union`: trace generated 2026-05-28, JSON `assembly_timestamp: 2026-02-26` — **3-month gap**. Counts diverge: parents 138 vs 167, findings 36 vs 30, tables 77 vs 61, figures 0 vs 43, monetary 32.2M vs 2.87M crore. `report_id`: `2025_4` (trace) vs `2025_04` (json).
- `CG_2025_1 Chhattisgarh`: trace 2026-05-29, JSON 2026-05-26 — 3-day gap. `report_id`: `CG_2025_01` (trace) vs `CG_2025_1` (json). Trace documents a catastrophically degraded run (1 parent, 124 children, 0 findings); JSON reflects an earlier successful run (132 parents, 990 children, 60 findings).
- `BR_2024_3 Bihar`: `report_id`: `BR_2024_03` (trace) vs `BR_2024_3` (json). Same PDF, two different IDs.
- `2023_20 Food_grains`: same-day re-run (JSON assembled 10:57, trace 16:27 same day); minor count drifts.

**Two independent causes:**

**Cause 1: Report-ID generation is non-deterministic across code versions.** The zero-padding behavior of the serial-number sanitizer changed at some point — `2025_4` became `2025_04`, `CG_2025_1` became `CG_2025_01`, `BR_2024_3` became `BR_2024_03`. The **same PDF processed by two pipeline versions produces two different filenames on disk**, and downstream tools have no way to know they're the same report.

**Cause 2: No mechanism ensures trace + JSON are from the same execution.** `--trace` can run against an older JSON on disk. If pipeline code has evolved since that JSON was assembled, the trace will narrate a *different* run than the one that produced the JSON — and the divergence is silent.

**Partial answer to the Bihar duplicate question** (the 9th report you dropped from this batch): we don't need the dropped 9th to answer it. The report_id zero-padding bug means **if the pipeline had been re-run on `BR_2024_03_Bihar.pdf` with the current code, it would have written `BR_2024_3_…json` while older artifacts on disk still bear the `BR_2024_03_…` name**. The "duplicate" wasn't two reports — it was the same report serialized twice under two different IDs because the sanitizer changed. Running the pipeline a third time today would produce a new artifact under whichever ID format current code emits, and there'd still be no deduplication mechanism. The fix is: deterministic report_id generation (always-zero-padded or never; pick one and embed it in `manifest_ingestion_service.py`), plus an existence check before writing.

### 2.5 Trace instrumentation has visibility gaps

**Reach: 8/8 reports.** Different gaps in different reports — but the trace emits wrong/missing data widely enough that it's a coherent issue in its own right. **Severity: P1** because it actively obscures real failures (the trace under-reports them) and creates false negatives.

| Instrumentation defect | Reports observed | Evidence |
|---|---|---|
| Phase 4 input `page_count: 0` (real value 134/146/108/226/56) | Union, GJ, Food_grains, NHAI, BR (5/8) | trace §Phase 4 Input field across these |
| Phase 4 emits `toc_quality=0` but Phase 5.5 reads `quality_before=50` | GJ, OD, Food_grains, NHAI (4/8) | trace §4 output vs §5.5 input |
| Phase 5.5 `reconciliation_strategy=unknown` despite `method=merged` | Union, Food_grains (2/8 confirmed) | trace §5.5 Mechanism |
| Phase 6 `figures: 0` while JSON has 43/50/16 image_caption chunks | Union, OD, Food_grains (3/8 confirmed) | trace §6 Output vs `json: content_type_distribution.image_caption` |
| `extraction_method: None`/"unknown" on all tables in structured_data | NHAI, CG, UK, OD (4/8 confirmed) | `json: child_chunks[?].structured_data.extraction_method` |
| `processing_status` stuck at "chunking_complete" despite Phase 8/9/10 running | Union, Food_grains (2/8) | `json: report_metadata.processing_status` |
| `errors_encountered: N` non-zero with no detail anywhere | Union (6 errors), Food_grains (9), OD (10 failed extractions) | `json: processing_stats.errors_encountered` |
| Phase 2 and Phase 3 entirely missing from trace | Union | trace Pass/Fail Summary |
| Phase 2 dual classification ("scanned" then "native_text") | BR, NHAI, Food_grains (3/8) | trace §Phase 2 |
| Phase 3 status "failed" with "OCR cache incomplete" on native PDFs | BR, NHAI | trace Pass/Fail row |
| Trace finding-sample `monetary` column always 0 (reads wrong field) | Food_grains | trace §9 samples |
| Phase 2 cache reconstruction emits no density figure | All reports using cached triage | trace §2 — `avg_chars` and ratio are absent |

**Specific code locations to wire:**
- `triage_service.py` — emit `avg_chars`, ratio, and dual-classification resolution
- `ocr_service.py` — Phase 3 emit, status checks classification before reporting
- `scaffolding_service.py` — Phase 4 input page_count
- `toc_reconciliation_service.py` — strategy reporting, quality score field naming
- `content_extraction_service.py` — figure count, error_log surfacing
- Phase 8 assembly — `processing_status` advancement, `errors_encountered` surfacing into trace
- StructuredTable creation path — `extraction_method` propagation

### 2.6 Section classifier dumps majority into 'other'

**Reach: 8/8 reports** (where measured). **Severity: P1** — affects analytics that aggregate findings by section.

| Report | Sections 'other' | % | Total sections |
|---|---|---|---|
| 2025_4 Union | 152 | 91% | 167 |
| UK_2025_06 | 152 | 91% | 167 |
| CG_2025_1 | 124 | 94% | 132 |
| 2023_20 Food_grains | ~120 | 74% | 163 |
| 2023_7 NHAI Toll | 71 | 69% | 103 |
| GJ_2024_03 | 34 | 65% | 52 |
| OD_2025_05, BR_2024_3 | Not specifically reported; pattern consistent |

**The classifier currently handles:** annexures, introduction, executive_summary, audit_objectives, audit_criteria, audit_scope, methodology, acknowledgement, findings, conclusion.

**The classifier doesn't handle (per `UK_2025_06` F06):** financial_management, employment, execution, planning, capacity_building, grievance_redressal, impact, monitoring_evaluation, recommendations sections, and most numbered topical chapter themes (e.g., "Chapter 5: Solid Waste Management Findings", "3.1 Funding Pattern").

**No red flag exists** for section-classification quality — only finding 'other' ratio is monitored. The two metrics correlate but aren't redundant: finding classification is per-observation, section classification is per-structural-unit.

### 2.7 Entity extraction noise

**Reach: 8/8 reports.** **Severity: P1.** Schemes lists are universally polluted; ministries and organizations less so.

| Failure mode | Examples |
|---|---|
| Stuttered/doubled text (no dedup) | "DirectDirect BenefitBenefit TransferTransfer Scheme", "NationalNational SocialSocial AssistanceAssistance Programme" (GJ) |
| Place names | "Anantapur" (Union) |
| Generic categories | "Capital Expenditure" (Union), "Information Technology", "Below Poverty Line" (GJ) |
| Acronyms expanded as schemes | "Know Your Customer" (GJ), "Computer Based Test" (Union) |
| Job titles / professional roles | "Chartered Accountant" (CG), "Block Resource Persons" (CG), "Block Education Officer" (OD) |
| Document-section names | "Chapter 3 of Union Government Financial Audit Report" (Union), "Annual Report on the implementation of the Scheme" (OD), "Annual Technical Inspection Report" (BR) |
| Sentence/phrase fragments | "Authorisers sign the Scheme" (GJ), "As envisaged in the Service Agreement" (Food_grains), "According to the Solid Waste Management" (BR), "Amount meant for Expenditure on Social Sector Scheme" (Union) |
| Verbose finding-like phrases | "Avoidable expenditure due to not using Linear Program" (Food_grains), "Benchmark Gross Freight Revenue" (Food_grains) |
| Equipment / objects misclassified as organizations | "Safety Guidelines Display Board" (OD) |

**Pattern:** the extractor accepts any title-cased noun phrase as a candidate scheme without verifying it carries a scheme marker (e.g., a "Yojana", "Mission", "Programme", "Scheme" suffix, or a parenthetical acronym `(XYZ)`). It also doesn't deduplicate stuttered text (the doubled-word phenomenon is consistent — suggests a tokenizer bug somewhere upstream that produces a token like "DirectDirect" which then survives entity matching).

---

## 3. Frequent Pattern Catalog — Issues Affecting 3–5/8 Reports

### 3.1 Multi-page table merger drops pages within merge groups

**Reach: ≥3/8 (Union, Food_grains, UK MGNREGA), likely more.** **Severity: P0** — silent data loss with no DLQ entry and no red flag.

- `2025_4 Union` (F02 P0): `parents[?] primary 108 has source_pages=[108,109,110,112]` — **skips page 111**. `primary 116 has [116,117,119,120]` — **skips 118**. Pages **114 and 115 entirely absent** from any chunk. Annexure 4.5 ("Savings ≥₹100 crore at Minor/Sub-head level") loses approximately 50 rows of substantive grant data covering Ministry of Housing & Urban Affairs, Water Resources, Drinking Water grants.
- `2023_20 Food_grains` (F01 P0): The §5.4 compliance review multi-page table on physical pp.119–127 — **pages 121, 124, 125, 126 = 0 chunks of any type**. Phrase probes confirm: "interest charges to the tune" (p125) and "recovery of abnormal storage" (p126) exist in PDF but appear nowhere in JSON. Tier-1 returned None → tier-2 returned near-empty → tier-3/Gemini was **skipped** (`items_identified=0` in Phase 10b) → no DLQ → no error flag.
- `UK_2025_06` (F04 P1): Multi-page merge handles only pairs of consecutive pages. The "Doubtful Attendance" / "Delayed Payment" appendix table (Appendix-5.7) spans pp.135–145 (11 pages). The pipeline captured pp.135–138, 141, 142 but **missed pp.140, 144, 145**. Multi-page merge stitched 138→139 and 142→143 as pairs but doesn't iterate across longer chains.

**Heuristic:** appears to be "accept only consecutive pages when column structure matches >80%". Three distinct failures:
1. Off-by-one — a single non-conforming page in the middle of a contiguous range breaks the stitch
2. Hard limit at 2 pages — tables spanning 3+ pages lose continuation pages
3. No fallback to tier-3/Gemini when tier-1 + tier-2 both produce zero or degraded output

**The compounding failure:** when tier-1 returns None and tier-2 produces a 2-row mega-cell blob (Food_grains), tier-3 doesn't fire because the layout heuristic decided a table existed at tier-2 (just badly), so Phase 10b sees `items_identified=0`. The recovery path was disabled by partial success.

### 3.2 Chapters / sections missing from L1 hierarchy

**Reach: 3/8 reports (OD ×2 chapters, GJ ×1 section, BR ×over-fragmentation pattern).** **Severity: P0** — entire chapter contents are mis-parented to adjacent chapters with no flag.

- `OD_2025_05` (F01 P0): **Chapters 1 AND 9 missing from Level-1 hierarchy.** "Chapter 1 Introduction" (pdf p.20) and "Chapter 9 Monitoring and Evaluation" (pdf p.138) detected as section-headers but assigned Level 2 instead of Level 1. All Chapter 1 children (8 paragraphs on pp.20–23) parented to Executive Summary [10,26]; Chapter 9 children parented to Chapter 8 [126,158].
- `GJ_2024_03` (F01 P0): Section 3.1 "Non-payment of Pension from the effective date" missing from parent chunks. Content from 3.1 (tables 3.1, 3.2, sub-section text, ~10 children) mis-parented under 3.2 "Stoppage of Pension due to failed transactions".
- `BR_2024_3` (F04 P1): Over-fragmentation in the other direction — 32 L1 entries vs ~5 real chapters. Sub-paragraph items like "(i) Loss of central share..." promoted to L1 with page ranges [88, 90] — which then absorb children from sections 5.4–5.9.

**Root cause:** Docling section-header level assignments are trusted without cross-checking against:
- Numbered chapter pattern ("Chapter N" should be L1)
- Printed TOC level (if available)
- Reasonableness against report length (more L1 than chapters = level miscalibration)

**The Phase 7.5 hierarchy_concentration metric does not catch these failures** because the absorbed children are *spread* across the absorbing parent's range — concentration stays low (3–6%) while the structure is wrong.

### 3.3 Triage misclassification on heavy front-matter PDFs

**Reach: 1/8 confirmed (`2025_4 Union`), likely more.** **Severity: P0** because it silently routes a native PDF through the scanned-PDF code path, skipping Tier-1 pdfplumber on text-stream-clean tables.

- `2025_4 Union` (F04 P0): Native PDF misclassified as `scanned` because the 10-page sample average is 83.9 chars/page (ratio 0.56). The PDF has 211,247 native non-whitespace chars overall (avg 1886 chars/non-blank page) — emphatically a native PDF. The 0.7–1.3 borderline band doesn't catch this: ratio 0.56 is below the lower bound, so no `borderline_classification` flag fires.

**Downstream consequence:** Phase 6 routed all 77 (trace) / 61 (json) tables to tier2_docling and skipped Tier 1 pdfplumber entirely. The Page 22 GDP table did extract cell-perfectly via Docling, but tier-1 on text-stream-clean annexure tables would likely have produced superior results — and the false-routing means tier-1 never had a chance.

**Heuristic fix needed:** when computing avg_chars, skip pages with 0 chars (or use median rather than mean) so blank-page-heavy front matter doesn't drag the sample below threshold. Alternative: sample mid-document pages rather than just first 10.

### 3.4 Rotated page (270°) handling

**Reach: 2/8 reports (OD, CG).** **Severity: P1.**

- `OD_2025_05` (F04 P1): Pages 150, 152, 154–159, 164 have `rotation=270°`. pdfplumber extracts reversed text — "lanoitcnuF" instead of "Functional", "smoorssalc" instead of "classrooms", "elbaliava" instead of "available". ~8 appendix tables completely unusable.
- `CG_2025_1` (F06 P1): 5 parent chunks have garbled OCR titles ("¢-xIpuody", "WNQWNC p'¢-xipuedy") from rotated landscape appendix pages. 71 children assigned beneath them.

**Pattern:** pdfplumber doesn't auto-handle 270° rotation. The page comes through with text positions but in reversed order, producing readable-but-reversed strings. No detection, no fallback. Tables either lost (OD) or hierarchy degraded (CG).

**Fix:** detect `page.rotation != 0` before pdfplumber extraction. Either pre-rotate the page or skip tier-1 and route directly to tier-2/3.

### 3.5 Recommendation extraction defects

**Reach: 4/8 reports (Union, GJ, BR, UK).** **Severity: P0 for Union, P1 elsewhere.**

- `2025_4 Union` (F03 P0): PDF p.13 lists 5 numbered "We recommend that: 1. ... 2. ... 3. ... 4. ... 5. ..." items in Executive Summary. Only #2 was extracted (twice, as a duplicate); #1, #3, #4, #5 lost. Recommendation 3 in the JSON is a false positive: "PAC26 was of the view that MoF should institute mechanisms..." — that's a Public Accounts Committee opinion citation, not a CAG recommendation. Verb-strategy regex matched on "should institute".
- `GJ_2024_03` (F04 P1): Recommendation 7 is a guideline citation: "The NSAP Guidelines (Paragraph 3.1.2) mandate the constitution of Special Verification Teams...". The verb strategy matched "mandate" without checking the leading clause.
- `BR_2024_3` (F05 P1): All 14 recommendations have `addressee=None, priority=None` despite explicit "ULBs may speed up...", "State Government may determine..." patterns in PDF.
- `UK_2025_06` (F07 P1): All 22 recommendations have `target_entity=None, priority absent`, 100% verb strategy. Structural strategy not firing on the "Recommendations" sub-sections that exist as headers (2.4, 3.9, 4.6, 5.11, 6.8, 7.7, 8.6).

**Three distinct failure modes:**
1. **Verb-strategy false positives** on PAC citations / Guideline citations / "should" used in normative-but-not-recommendation contexts.
2. **Structural-strategy not detecting "Recommendations" sub-sections** as bounded recommendation lists.
3. **Numbered-strategy missing** "We recommend that:\n 1. ...\n 2. ...\n" list patterns.
4. **Addressee/priority extraction broken everywhere** — the patterns "[Entity] may [action]", "[Entity] should [action]" aren't being mined for the addressee field.

### 3.6 Year extraction bugs

**Reach: 2/8 confirmed (GJ, Food_grains), pattern is systematic.** **Severity: P1.**

- `GJ_2024_03` (F02 P0): `report_year=2025` instead of 2024. PDF cover says "Report No. 03 of 2024"; report covers audit period 2017–21. Likely extracting from `publication_date` (which is 2025-03-28) rather than the report title.
- `2023_20 Food_grains` (F13 P2): `report_year=2024` from publication_date conflicts with `report_no: "20 of 2023"` and `report_id: 2023_20`.
- `BR_2024_3`: report_year=2024 was actually correct (audit period ended March 2022, report published 2024). Cross-check confirms the bug pattern but didn't trigger here.

**Fix:** prefer `report_no` / `report_id` year over `publication_date` for `report_year`.

### 3.7 Duplicate parent chunks

Already covered in §2.3.F — but worth pulling out separately because the fix is local and tractable:
- Add a deduplication pass in Phase 7 parent creation: if two parents share the same `toc_entry` (or normalized title) and overlapping page ranges, keep only one (prefer deeper-level entry or earlier-in-document position).

---

## 4. Tier-Specific Findings

### 4.1 Union-tier specific
- **Finding taxonomy lacks `accounting_irregularity`, `non_realization_of_dues`, `system_deficiency`** (state/local-only currently). Union Financial Audit reports are dominated by these patterns; result: 86.7% of `2025_4 Union` findings go to 'other'. Either expose these types to Union profile, or add Union-specific patterns.
- **State/Local-only types incorrectly assigned to Union reports.** `2023_20 Food_grains` (F08 P2) has findings typed as `idle_assets`, `incomplete_infrastructure`, `accounting_irregularity` despite being union-tier. Gate the finding-type taxonomy by detected tier, not just severity thresholds.

### 4.2 State-tier specific
- State reports are more likely to have multi-page appendix tables that span 3+ pages (UK MGNREGA: 11-page appendix). Multi-page handler needs to iterate chains, not just pairs.
- State reports more frequently have 270°-rotated landscape appendix pages (OD, CG).
- State performance audit chapters have topical themes (financial_management, employment, capacity_building, grievance, impact) that the section classifier doesn't recognize.

### 4.3 Local-body-tier specific
- Scanned PDFs are concentrated here (CG_2025_1 fully scanned). The Phase 5.7 LLM validator was designed for low-quality TOC reports — but it extracts text from the raw PDF (not OCR'd) and gets nothing on scanned reports. `CG_2025_1` (F04 P1): Phase 5.7 fired on a scanned PDF, called the LLM with empty text, returned 0 entries, wasted the API call.
- Local-body reports have many appendix tables; appendix mis-parenting affects 12/20 in `BR_2024_3`.
- `idle_assets`, `fund_utilization_failure`, `incomplete_infrastructure` types exist for local but are under-utilized; `BR_2024_3` had `non_compliance` and `system_deficiency` patterns that didn't fire on local-specific vocabulary (UC non-submission, no committees, ULB-vs-PRI distinctions).

---

## 5. The Bihar Duplicate Question — Resolved

You dropped the 9th report (the intentional `2024_03_Bihar` duplicate) and were unsure if the duplicate question could be answered from 8. **It can.** The mechanism that would have caused the "duplicate" is already visible across 4 of the 8 reports:

**The report_id sanitizer changed between code versions.** Concrete evidence:
- `2025_4_…` (Union trace) vs `2025_04_…` (Union JSON, 3 months older)
- `CG_2025_01_…` (CG trace) vs `CG_2025_1_…` (CG JSON, 3 days older)
- `BR_2024_03_…` (Bihar trace) vs `BR_2024_3_…` (Bihar JSON)

If you had run the pipeline on the same Bihar PDF twice — once under the old code (writing `BR_2024_03_…json`) and once under the current code (writing `BR_2024_3_…json`) — you'd have ended up with two artifact files on disk for one source PDF. That's the "duplicate". It's not two reports; it's one report under two filenames because the ID generator isn't deterministic across versions.

**Three things follow:**
1. The 9th report was the wrong test. Both halves would carry the same instrumentation bugs and reveal nothing new.
2. The fix is in `manifest_ingestion_service.py` and `parsing_config.yaml`: pick an exact report_id format (recommendation: zero-pad to 2 digits, so `2025_04`, `BR_2024_03`, `CG_2025_01`), encode it as a config constant, and add a regex assertion on emission.
3. Add an existence check before writing: if a JSON exists for either the canonical or the legacy ID, log a warning. Optionally, a one-time migration script to canonicalize older filenames.

---

## 6. What's Working — Protect These Wins

The pipeline isn't broken end-to-end. The structural skeleton is solid; the breakage is concentrated in Phases 5.5 (output validation), 6 (multi-page table merger + rotation handling), and 9 (semantic enrichment). The following components are consistently strong:

- **Phase 1 Manifest Ingestion** — tier detection, state code mapping, PDF resolution were correct in all 8 reports.
- **Phase 4 bookmark rejection on assembly artifacts** — the assembly-pattern penalty correctly rejected garbage bookmarks in NHAI, Food_grains, GJ, BR, CG (`01 Cover`, `Blank Page`, `WBOCW_*`, file-merger labels with page=-1, etc.). The 60.0 threshold and 70%–100% rejection rates were appropriate signals every time. One concern: in `UK_2025_06` the score landed at exactly 64 (just over 60) despite 14 "Blank Page" + 9 "15_Separator" entries — the penalty needs strengthening, but the mechanism is right.
- **Phase 4 → 5.5 rescue path** — Phase 5.5's ability to recover hierarchy from zero-quality starting points (4 reports went 0→98/99/100) is genuinely impressive and irreplaceable for the bookmark-less / assembly-artifact-bookmark common case. The pollution issue (§2.3) is fixable without removing the rescue.
- **Phase 5.7 LLM cost gate** — correctly skipped on every high-quality TOC; correctly fired on `CG_2025_1` (scanned, quality 0). The gate logic is sound. The only concern is the "fabricated 100" case (§2.3) which is upstream of 5.7, not 5.7's fault.
- **Phase 6 Tier-1 on native text-stream tables** — when triage classifies correctly and tables are simple, pdfplumber produces cell-perfect output (`2025_4 Union` p.22 GDP table; `GJ_2024_03` table 3.4 stoppage of pension; `BR_2024_3` table 1.1 important statistics). The tier ladder works when its input is right.
- **Phase 7 child-to-parent assignment** — **0% unassigned children in all 8 reports across 6,222 total child chunks**. Strongest part of the pipeline.
- **Phase 7 multi-page table merging for 2-page cases** — works correctly when the table spans exactly 2 consecutive pages with matching columns. Annexure 3.2 in `2025_4 Union` (71 rows × 6 cols, pp.80–81) cleanly merged. The 3+ page case is the bug.
- **Phase 7.5 concentration metric** — skips correctly when concentration is genuinely low (all 8 had concentration <12%). The metric is right; it just isn't comprehensive (doesn't catch level misassignment, empty parents, duplicates).
- **Phase 8 report metadata** — most fields populated correctly across reports (`report_id`, `tier`, `state_name`, `report_type`, `publication_date`). Issues are localized to `report_year` (§3.6) and `processing_status` (§2.5).
- **Phase 9 severity tiering** — tier-specific thresholds (Union ≥₹100 cr, State ≥₹50 cr, Local ≥₹10 cr) applied correctly. The criticality of severity output is just downstream of the broken monetary inputs.
- **Phase 9 executive_summary_index** — `2025_4 Union` extracted 28 items with 19/20 citations resolved (95% rate). Strongest semantic-enrichment subcomponent.
- **Phase 9 cross-reference resolution** — 66 in Union, 55 in Food_grains, 214 in OD, several across all reports. Generally healthy.
- **Phase 9 annexure linking** — populated in Union (30 links) and others.
- **Phase 10c TOC filtering** — correctly identified TOC tables masquerading as data tables across reports (46 in GJ, 18 in BR, 5 in NHAI, 1 in Food_grains).

---

## 7. Prioritized Action Roadmap

Action items grouped by priority. Each carries: (a) the report(s) where evidence was strongest, (b) the code location surfaced in per-report investigations, (c) the proposed fix. This is the section to hand to Claude Code.

### 7.1 P0 — Data Integrity Bugs (fix first)

**P0-01. Monetary extraction overhaul.** All 8 reports.
- Path: monetary processor (likely `src/parsing_pipeline/modules/semantic_enrichment_service.py` or a sub-extractor; per-report docs reference `monetary_processor`).
- Subtasks:
  - Dedup `monetary_values` by (amount, unit, paragraph-span-offset) before summing — fixes Food_grains, OD, BR (§2.1.B).
  - Add Indian comma-grouping support: `r"₹?\s?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\s+crore"` covers both `₹2,41,220.26 crore` and `₹241,220.26 crore` — fixes Union (§2.1.D).
  - Reject year-like patterns: `r"(?:rs|₹)\s?(?:19|20)\d{2}\b(?!\.\d)"` should not match — fixes BR (§2.1.E).
  - Use explicit-total parsing for per-unit × count cases: when finding text contains both "₹X per unit" and "Y beneficiaries/units/cases", prefer an explicitly stated total over the product — fixes GJ (§2.1.C).
  - Populate per-finding `monetary_value` (singular) from the largest entry in `monetary_values` — fixes Union, UK (§2.1.A).
  - Compute `total_monetary_crore` aggregate by summing per-finding values, not by independent regex pass over chunks — fixes Union's three-way disagreement (§2.1.G).
  - Populate `monetary_aggregates` dict from `statistics.findings.by_type` — fixes NHAI, OD, Food_grains, Union (§2.1.F).
  - Add a sanity-check red flag: if `total_monetary_crore` > tier-specific implausibility threshold (e.g., 10× the largest historical monetary aggregate for that tier), fire a `monetary_total_implausible` flag. Catches BR's ₹318K cr and Union's ₹322L cr (§2.1.H).
- Re-derive severity after monetary fixes — fixes Food_grains false CRITICALs.

**P0-02. Phase 5.5 output validation pass.** All 8 reports.
- Path: `src/parsing_pipeline/modules/toc_reconciliation_service.py`.
- Add a candidate-rejection filter before merging Docling section-headers, rejecting entries that match:
  - Parenthetical paragraph citations: `r"^\([Pp]aragraphs?\s+[\d.]+\)?\s*$"`, `r"^\([Ss]ource:?\s.*\)$"`
  - Running-header patterns: `r"^Report\s+No\.\s+\d+\s+of"`, `r"^Page\s+\d+$"`
  - List-item fragments: `r"^[a-z]\.\s+"`, `r"^\([ivxlcdm]+\)\s+"` when in mid-document (these are valid only as deep children, not parents)
  - Encoded-font ranges: entries where >30% of characters are non-ASCII-printable or outside expected Unicode ranges
  - Single-token stubs: entries with <3 readable words
- Cap the post-reconciliation quality score at a value that allows Phase 5.7 to still fire (recommendation: cap at 85) — fixes the fabricated-100 cases in Food_grains, GJ, OD.
- Deduplicate parents within the same hierarchy by (normalized_title, overlapping_page_range) — fixes NHAI, Union, OD, GJ duplicate parents (§2.3.F).
- Fix the inverted comparison: `if quality_score >= high_threshold` (70) → "high", `elif >= medium_threshold` (40) → "medium", `else` → "low". The trace's reason string for BR (`quality_score=70 < medium_threshold=40 → low`) is logically broken either way — verify both the code and the trace formatting.
- Add a numbered-chapter promotion pass: any section-header matching `r"^(Chapter|CHAPTER)\s+([IVX]+|\d+)\b"` is forced to Level 1 — fixes OD's missing Chapters 1 & 9 (§3.2).

**P0-03. Multi-page table merger overhaul.** Union, Food_grains, UK.
- Path: `src/parsing_pipeline/modules/multi_page_table_handler.py`.
- Iterate stitching across chains of any length (current implementation pairs only). Algorithm: starting from a page-1 table, keep advancing while next page contains a table with ≥80% matching column structure.
- Tolerate 1 non-conforming page in the middle of a chain (a header continuation, a page break) — fixes Union's pages 111 and 118 skips.
- When tier-1 returns None and tier-2 produces low-quality output (e.g., 2 rows, mega-cells, null `row_count`/`col_count`), route to tier-3/Gemini rather than accepting tier-2's partial result. Don't let partial-success in tier-2 disable tier-3.
- When a page in a layout-detected multi-page table region has 0 surviving chunks, route it to DLQ + emit a `multi_page_table_page_lost` red flag. Catches Food_grains's lost pages silently.

**P0-04. Section/Chapter L1 promotion guardrails.** OD (Chapters 1 & 9), GJ (section 3.1).
- Path: Phase 5.5 or Phase 7 (parent creation).
- After Phase 5.5 reconciliation: enforce that any heading matching `r"^Chapter\s+\d+"` or `r"^CHAPTER\s+[IVX]+"` becomes Level 1.
- Sanity check: if `count(L1_parents) > 2 × count(printed_TOC_chapters_if_known)` or `> 15` absolutely, log a warning and run a level-reassignment pass.
- Cross-check L1 promotion against numbered-section pattern: section "3.1" with no "3.0" or "Chapter 3" L1 ancestor in the hierarchy is suspicious.

**P0-05. Triage misclassification on heavy front-matter PDFs.** Union.
- Path: `src/parsing_pipeline/modules/triage_service.py`.
- When computing avg_chars over the sample window, skip pages with 0 chars (or below a "blank page" threshold like <20 chars). Alternatively, use median over the sample. Alternatively, expand the sample window (currently 10) to 20–30 or sample from mid-document.
- Widen the borderline band: instead of 0.7–1.3, use 0.4–1.5. This catches the Union case (ratio 0.56) for review rather than silently classifying as scanned.
- Resolve dual-classification cache emissions (BR, NHAI, Food_grains): emit only the final authoritative decision in trace.

**P0-06. Deterministic report_id generation.** 4/8 reports.
- Path: `src/parsing_pipeline/modules/manifest_ingestion_service.py`.
- Pick a canonical format. Recommendation: `{state_or_blank}{year}_{NN}_{title_slug}` with `NN` always 2-digit zero-padded.
- Encode as a regex assertion at the point of emission: `assert re.match(r"^([A-Z]{2}_)?\d{4}_\d{2}_.+", report_id)`.
- Add an existence check before writing JSON: if a file exists for either the canonical or a legacy variant, log a warning.
- Optional: one-time migration script (`scripts/canonicalize_report_ids.py`) that walks `data/processed/` and renames legacy-format files to canonical, updating any cross-references.
- Add `assembly_timestamp` to the trace header so trace ↔ JSON provenance is verifiable. Optionally, refuse to write a trace when the JSON's `assembly_timestamp` is older than N hours (suggests a stale-JSON run).

### 7.2 P0 — Heuristic Tuning

**P0-07. Finding-type classifier — pattern library expansion.** All 8 reports.
- Path: `src/parsing_pipeline/modules/semantic_enrichment_service.py` (finding extractor patterns).
- Add patterns (regex examples are illustrative — actual implementation should use phrase-anchored matching):
  - `r"\b[Aa]udit\s+(observed|noticed|found|compared|verified)\s+that\b"` + deficiency_keyword → match-the-deficiency-keyword-type (umbrella)
  - `r"\bwas\s+not\s+(maintained|done|adhered|prepared|established|implemented)\b"` → `non_compliance`
  - `r"\bshortfall\b|\bagainst\s+the\s+target\b|\bX\s*%\s+(vs|against|as\s+against)\s+Y?\s*%"` → `performance_shortfall`
  - `r"\btransferred\s+as\s+loan\s+from\b.*\bto\b"`, `r"\butilized\s+for\s+inadmissible\b"` → `diversion_of_fund`/`irregular_expenditure`
  - `r"\bno\s+\w+\s+(in\s+any|established|constituted)\b"` → `system_deficiency`
  - `r"\bUC[s]?\s+(non[-\s]?submission|not\s+furnished)\b"`, `r"\bunreconciled\s+accounts\b"` → `non_compliance`
  - `r"\bcollected\s+₹[\d.,]+\s+(?:crore|lakh).*\bvs\.?\s+expenses\b"` → `loss_of_revenue`
  - `r"\b(extra|avoidable)\s+expenditure\b"` → `wasteful_expenditure`
  - `r"\bunutilised?\s+(land|assets|funds)\b"` → `idle_assets`
- Add tier-specific type taxonomy gate: expose `accounting_irregularity`, `non_realization_of_dues`, `system_deficiency` to Union profile (with Union-tuned patterns); restrict `idle_assets`, `incomplete_infrastructure` to local. Currently `2023_20 Food_grains` (Union) emitted findings typed as `idle_assets` — that should not happen.
- **Non-finding rejection patterns** (false-positive guard):
  - `r"^\s*Brief\s+Snapshot\b"` → not a finding
  - `r"^\s*[\d.]+\s+denotes\b"` → footnote/definition, not a finding
  - Pure background paragraphs in Chapter 1/Introduction that don't contain a deficiency keyword

**P0-08. Recommendation extraction overhaul.** 4 reports.
- Path: same module's recommendation extractor.
- **Structural strategy** (currently underused): detect "Recommendations" / "X.Y Recommendations" sub-section headers; extract bounded list of children as recommendations. Fires for UK MGNREGA chapters 2.4, 3.9, 4.6, 5.11, 6.8, 7.7, 8.6; BR chapter conclusion recommendations.
- **Numbered list-after-cue strategy**: detect `We\s+recommend\s+that:?\s*\n\s*1\.` and extract the numbered items that follow. Fixes Union (5 recommendations missed).
- **Verb-strategy rejection patterns** (false-positive guard):
  - Preceded by `"PAC\d*\s+(was\s+of\s+the\s+view|recommended)"` → not a CAG rec (it's a citation of PAC opinion).
  - Preceded by `"The\s+\w+\s+Guidelines"` or `"Paragraph\s+[\d.]+\s+(mandates|states|requires)"` → not a rec (it's a citation of existing rules).
- **Addressee extraction**: regex `r"(?:^|\.\s+)(?:The\s+)?([A-Z][\w\s&]+?)\s+(?:may|should|shall|must)\s+"` to populate `addressee`/`target_entity` field.
- **Deduplication**: same recommendation appearing in Executive Summary + body → keep one.

**P0-09. Section classifier — type taxonomy expansion.** All 8 reports.
- Path: section classifier module.
- Add type patterns for state/local report chapter themes: `financial_management`, `employment`, `execution`, `planning`, `capacity_building`, `grievance_redressal`, `impact`, `monitoring_evaluation`.
- Add a section_other_ratio red flag at threshold 70% (parallel to the finding flag at 30%). The two metrics correlate but section classification is more structurally robust to fix.

### 7.3 P1 — Quality & Polish

**P1-10. Entity extraction filters.** All 8 reports.
- Add a deduplication pass for stuttered text (`DirectDirect BenefitBenefit`) — likely a tokenizer artifact that needs investigation upstream.
- Reject entities that:
  - Start with a preposition (`According to`, `As envisaged in`)
  - Are bare place names (cross-check against a places list)
  - Are job titles or professional roles (`Block Education Officer`, `Chartered Accountant`)
  - Are document-section names (`Chapter X of`, `Annual Report on`)
  - Lack a scheme marker AND lack an acronym in parens: require either a `Yojana|Mission|Programme|Scheme` suffix OR a `(XYZ)` parenthetical acronym.

**P1-11. Page rotation handling.** OD, CG.
- Path: `src/parsing_pipeline/modules/content_extraction_service.py` and/or tier-1 wrapper.
- Detect `page.rotation != 0` before pdfplumber call.
- Pre-rotate the page (PyMuPDF `page.set_rotation(0)` on a copy) before passing to pdfplumber, OR skip tier-1 entirely and route to tier-2/3 for rotated pages.

**P1-12. Year extraction.** GJ, Food_grains.
- Path: Phase 8 / metadata extraction.
- Prefer `report_no` / `report_id` year over `publication_date`. Regex: `r"^(?:[A-Z]{2}_)?(\d{4})_"` from report_id, or extract from `Report No\.\s*\d+\s+of\s+(\d{4})` in the title.

**P1-13. Finding source attribution.** UK, OD.
- Path: finding extractor.
- Populate `source_section` (from the parent's `toc_entry`) and `source_page_physical` (from the source chunk's page) when constructing each finding. Currently all 116 findings in OD and all 46 in UK have these empty.

**P1-14. Phase 10b/10c hydration.** Union, CG.
- Ensure Phase 10b runs against the assembled JSON and replaces `image_caption` chunks' `content` (currently file paths like `data/extraction_images/.../picture_p0_228_98.png`) with Gemini-generated descriptions.
- Fail loudly when Phase 10c reports `phase_10c_complete` but `image_caption.content` still starts with `data/extraction_images/` — that's a false-completion signal.
- Populate `visual_asset_registry.tables_by_section` and `figures_by_section` during Phase 8 — these are empty dicts in multiple reports despite totals being correct.

### 7.4 P1 — Trace Instrumentation

**P1-15. Instrumentation gap closeout.** All 8 reports.
- Path: across `triage_service.py`, `ocr_service.py`, `scaffolding_service.py`, `toc_reconciliation_service.py`, `content_extraction_service.py`, Phase 8 assembly.
- Specific wires (each from §2.5):
  - `triage_service.py`: emit `avg_chars`, `ratio`, threshold; resolve dual-classification before emit
  - `ocr_service.py`: Phase 3 emit `skipped` (not `failed`) when classification is `native_text`
  - `scaffolding_service.py`: Phase 4 input — wire `page_count` from `DocumentTask`
  - `toc_reconciliation_service.py`: reconcile `quality_before` field name with Phase 4's `toc_quality`; emit actual strategy (`supplement`/`merge`/`replace`/`none`) rather than `unknown`
  - `content_extraction_service.py`: count `image_caption` / `Picture` blocks toward `figures` in §6 output; surface entries from `error_log` as Phase-6 errors in trace
  - Phase 8: advance `processing_status` after writing; surface `errors_encountered` count + details into trace
  - StructuredTable creation: populate `extraction_method` field from the tier that produced each table
- Phase 6 status decision: use `failed_count == 0` instead of `has_errors == False` to set `success` vs `partial` (per `TRACE_INSTRUMENTATION.md §Troubleshooting`'s known issue — confirmed in BR Bihar Check 3).

**P1-16. Provenance assertion in trace.**
- Embed `assembly_timestamp` (read from existing JSON if present) in trace front-matter.
- If trace is being generated and the on-disk JSON's timestamp is older than the current pipeline-code-build timestamp, log a warning that trace ↔ JSON may diverge.

### 7.5 P2 — Polish

**P2-17.** OCR header normalization: `CHAPTER ITI` → `CHAPTER III`; `144 CFC` → `14th CFC`; Roman-numeral corrections after `CHAPTER`. (CG)

**P2-18.** Pre-check before extraction on blank pages: if a layout-detected Table block sits on a page with <50 chars of text, skip extraction. Prevents wasted tier-3 calls. (UK page 104)

**P2-19.** Empty-parent cleanup post-Phase 7: remove parents with 0 children that match assembly-artifact name patterns. (UK 33/167, Food_grains 21/163)

**P2-20.** Fix `footnote_index` type: spec says dict, JSON emits empty list `[]` in Food_grains.

**P2-21.** Temporal extraction guards: bound `reference_years` to ≤ `report_year`. (Food_grains: reference_years included 2025/2026/2027 for a 2022 report.) Parse fiscal `YYYY-YY` end as the later year. (Food_grains: audit_period end_year=2021 should be 2022 for "2021-22").

### 7.6 New Extractor / Architectural Work (lower urgency, larger scope)

**NE-22. Phase 5.7 path for scanned PDFs.** `CG_2025_1`. Phase 5.7 currently extracts text from raw PDF and gets nothing on scanned reports. Use `ocred_pdf_path` if available, or pre-check that text extraction yields ≥100 chars before making the API call.

**NE-23. Printed-TOC detection on scanned PDFs.** `CG_2025_1` has a clean tabular TOC on pp.3–5 that pdfplumber can't read (image-only pages). After OCR, re-run Phase 4 on OCR'd pages, or feed OCR'd TOC-page text to Strategy 1/2.

**NE-24. Brief Snapshot / Background-prose detection.** Most CAG reports have "Brief Snapshot" boxes at the start of each chapter and contextual background paragraphs in Chapter 1. These are currently extracted as findings by the broad `audit_revealed` pattern. Specific detector module to exclude these from finding extraction.

**NE-25. Cross-reference resolver for sections with chapter prefix variation.** Some reports refer to "Para 3.5.4.2" vs "Paragraph 3.5.4.2" vs "section 3.5.4.2" — current resolver handles most but cleanup work remains.

---

## 8. Open Questions for You

1. **Workflow confirmation for the Bihar mismatch:** Were the JSONs you analyzed re-generated alongside the traces, or was `--trace` run against existing JSONs on disk? If the latter, the trace ↔ JSON divergence is partly an artifact-collection issue on top of the real report_id bug. Either way, P0-06 stands.

2. **Severity tiering target:** When the monetary fixes land, do you want a one-shot re-run on the 8 stress reports to verify the severity counts stabilize, or do you want the eval harness (deferred earlier) built first so this regression check happens automatically?

3. **Code path verification:** I've inferred several file locations from the per-report investigations (`monetary_processor`, `multi_page_table_handler.py`, `toc_reconciliation_service.py`, etc.). Some are direct mentions; others I've inferred from the screenshots of `src/parsing_pipeline/modules/`. Before Claude Code runs P0 fixes, it should `grep` to confirm the exact symbol locations — the diagnoses are sound but the paths are confident-but-not-verified.

4. **The 9th report decision:** I noted in §5 that the dropped Bihar duplicate wouldn't have added information (the report_id bug is fully diagnosable from the existing 8). If you have time/capacity later, a *different* 9th — e.g., a recent local-body report with heavy 270°-rotation OR a Union compliance audit with annexure multi-page tables >5 pages — would test fixes P1-11 and P0-03 respectively in production. Not a blocker for proceeding.

5. **Eval harness scope:** The original handoff deferred this. After P0 fixes, you'll need a regression check. The minimum viable harness is: the 8 current JSONs + ground-truth annotations (monetary totals, finding counts by type, chapter L1 list, list of pages with content) → a script that diffs new pipeline output against these. Want me to scope that as a follow-up, or do you want to write it directly via Claude Code from the metrics blocks in the 8 per-report docs?

---

## 9. Aggregate Statistics

For quick reference when prioritizing:

- **Reports affected by each P0 issue:**
  - Monetary extraction broken: 8/8
  - 'Other' finding ratio >30%: 8/8
  - Phase 5.5 injects noise: 8/8
  - Trace/JSON provenance mismatch: 4/8 (+ 1 same-day re-run)
  - Multi-page table page-drop: 3/8 confirmed (pages-lost cases)
  - Chapter/section missing from L1: 3/8

- **Cumulative silent data loss confirmed:** at least 11 pages of substantive content (Union pp.111, 114, 115, 118; Food_grains pp.121, 124, 125, 126; UK pp.140, 144, 145) — and these are just the pages cross-checked against the PDF. The true count is likely higher.

- **Cumulative monetary inflation across the corpus:** difficult to quantify precisely because each bug has a different multiplier, but conservatively: Food_grains overcounts ~₹6,300 cr; OD overcounts ~₹3,000+ cr; BR's ₹318,109 cr total is ≥99% inflated (real value likely <₹3,200 cr); Union's per-finding monetary_value is entirely missing. Treat any aggregate `total_monetary_crore` as unreliable until P0-01 lands.

- **Sample of 'other' findings tested against PDFs:** 47 findings sampled across reports; **38 of 47 (81%) were genuinely classifiable** if the typology and patterns existed; **6 of 47 (13%) were false-positive findings** (preamble paragraphs, brief snapshots, footnote definitions, background context); **3 of 47 (6%) genuinely belonged in 'other'**.

---

*Report generated from 8 single-report investigations: `2025_4 Union Financial Audit`, `2023_20 Food_grains`, `2023_7 NHAI Toll`, `GJ_2024_03 NSAP/DBT`, `UK_2025_06 MGNREGA`, `OD_2025_05 School Education`, `CG_2025_1 Chhattisgarh`, `BR_2024_3 Bihar`. Cross-references in this report use `{ReportID} {FindingID}` for specific evidence and `§X.Y` for sections within this document.*
