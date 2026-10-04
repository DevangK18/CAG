# Deep dive: monetary parsing

Owner: main session. Status: code analysis, test harness and real-output measurement are
done. The check of the "impact amount" choice against the gold labels is pending.

## Files

| File | Read | Role |
|------|------|------|
| `enrichment/monetary_processor.py` | all 744 lines | Parser |
| `finding_extractor.py:771-856, 1017-1059` | yes | Main consumer |
| `semantic_enrichment_service.py:780-930` | yes | Dedup and statistics |
| `assembly_service.py:1095-1110` | yes | Chunk metadata |
| `src/rag_pipeline/embedding_service.py:505-512` | yes | Qdrant payload |
| `src/entity_graph/mention_indexer.py:255-259` | yes | Entity graph |

Scripts:
- `scratchpad/step2/main/money_harness.py`: 27 edge cases.
- `scratchpad/step2/main/money_real.py`: run over all 1,204 findings in the 26 outputs
  (numbers below).

## Parser defects (verified by running the parser)

The harness fails 14 of 27 cases. One case in the harness had a wrong expectation (`Rs 50
thousand`) and parses correctly.

| # | Defect | Location | Example → parsed | Real-output impact |
|---|--------|----------|------------------|--------------------|
| M1 | "lakh crore" read as lakh | `MONETARY_PATTERNS` `:85-94` stops at the first unit | `₹1.5 lakh crore` → ₹1.5 lakh (0.015 crore instead of 1,50,000 crore) | 27 finding amounts 10⁷× too small; 298 "lakh crore" mentions in 7 union PDFs (FRBM and Union Accounts reports: 2025_03 ×113, 2024_01 ×86, 2025_18 ×69) |
| M2 | `million` and `billion` multipliers 10× too large | `UNIT_MULTIPLIERS` `:268-269` (the comments say "≈10 lakh" / "≈100 crore" but the values are 1 crore / 1,000 crore) | `₹ 3 billion` → 3,000 crore (should be 300) | 0 in current findings (latent) |
| M3 | Quantities read as money | the unit-only pattern `([\d,]+)\s*(crore\|lakh)\b` `:93` has no currency guard | `24.53 lakh certified candidates` → ₹24.53 lakh; `4.98 lakh sq. ft.` | ≥ 24 finding amounts (conservative regex count); Step 1 found 26 in OD alone |
| M4 | `Rs` matched inside words | `Rs\.?\s*…` with IGNORECASE and no word boundary `:90` | `members 25` → ₹25; `ITRs9` → ₹9; `years17` → ₹17 | 8 in findings; footnote numbers after "years", "Chapters", "ITRs" become rupees |
| M5 | Ranges lose their unit | each match is independent | `₹5 to ₹10 crore` → ₹5 (rupees) + ₹10 crore | tiny amounts appear; the range minimum is lost |
| M6 | Distinct amounts dropped as "duplicates" | 5% tolerance dedup on the same unit `:317-326` | `₹10.2 crore and ₹10.5 crore were paid` → only ₹10.2 crore | silent loss of real amounts |
| M7 | No `$`/USD handling | none | `$2 million` → nothing | minor |
| M8 | "₹ in crore" table units not applied | table chunks are excluded from findings | | only matters once tables feed findings |

## Aggregation defects (how parsed amounts are used)

| # | Defect | Location | Impact |
|---|--------|----------|--------|
| M9 | **Finding total = sum of every amount in the chunk.** Nested amounts ("₹25,208.86 crore, of which ₹15,668.71 crore …") and context amounts are added together | `finding_extractor.py:796` | 293 of the 495 multi-amount findings have total > 1.5 × max. `total_amount_inr` is inflated for them |
| M10 | **Severity comes from the inflated sum** | `finding_extractor.py:799`, `:1035-1048` | explains P9-04: JH 29/33 critical, 2025_16 40/43 critical |
| M11 | **The context and primary-amount logic exists but is dead code.** `extract_with_context`, `_classify_context`, `_identify_primary` and `get_primary_amount` (`monetary_processor.py:497-744`, ~250 lines) are never called; only `extract_monetary_values_with_preference` is used | grep: no callers outside the file | The "impact vs context" classification that would fix M9/M10 was built and never wired in |
| M12 | `_apply_explicit_total_preference` changes nothing in the common case; its 10× branch only logs at debug | `:448-476` | no effect |
| M13 | **Field names say INR, but the values are paise:** `normalized_inr`, `total_amount_inr` | `data_contracts.py:351, 366` | a consumer trusting the name is 100× off |
| M14 | **The entity graph treats `total_amount_inr` as rupees:** `amt / 10_000_000` gives "crore" | `src/entity_graph/mention_indexer.py:257-258` | every entity-mention amount is 100× too large |
| M15 | Chunk metadata mixes the two: `total_amount_crore` = the finding's **max**, `total_amount_inr` = the **sum** | `assembly_service.py:1103-1104` | the two fields disagree for 293 findings |
| M16 | The report headline total uses the max per finding, deduped by exact amount | `semantic_enrichment_service.py:885-892` | better than the sum, but it still counts false-positive findings (see `llm_validation.md`) and M1/M3 values. Cross-finding dedup (`:780-870`) groups by the summed `total_amount_inr` within 1%, which mostly finds nothing when sums differ |
| M17 | `_validate_monetary_value` uses `assert` for the checks | `:370-375` | assertions vanish under `python -O` |

## Proposed fixes

1. **Rewrite the amount regex into one tokenizer pass** (no longer 5 overlapping patterns):
   - currency prefix `(₹|Rs\.?|INR|`)` with a word boundary: `(?<![A-Za-z])Rs\.?`;
   - the number, allowing Indian grouping;
   - an optional compound unit `(lakh crore|thousand crore|crore|lakh|thousand|million|billion)`.
2. **Accept unit-only amounts (no ₹) only when the unit is not followed by a noun** within ~3
   tokens, and not when a quantity word follows. Better: require a currency marker within the
   same clause, or a table-header unit context.
3. **Ranges:** `₹X to (₹)Y unit` / `between ₹X and Y unit` gives both amounts the unit.
4. **Fix the multipliers:** million = 10⁶ rupees = 10⁸ paise; billion = 10⁹ rupees = 10¹¹ paise.
   Add lakh crore = 10¹² rupees = 10¹⁴ paise.
5. **Dedup only on exact span overlap** (the same text matched by two patterns), never on nearby
   values.
6. **Wire in context classification** (`extract_with_context` / `_identify_primary`, after fixing
   its patterns) and set:
   - `monetary_value` = the primary impact amount (not max, not sum);
   - `total_amount_inr` → rename to `total_amount_paise`, or drop it; if kept, sum only the
     amounts classified as impact, and exclude nested "of which" parts;
   - severity computed from the primary impact amount.
7. **Or use the LLM validator's new "impact amount" field** (redesign in `llm_validation.md`):
   the LLM picks which span is the impact amount, and the regex parser only normalises it. This
   is more robust than context regexes for nested state-finance prose. Decide after measuring
   both against the gold `impact_amount` labels.
8. **Rename paise fields** or add explicit `_paise` / `_crore` pairs everywhere. Fix
   `mention_indexer.py:257`.
9. **Add a unit-test file** from the harness cases, extended with real failures from the gold
   set.

## Pending

Compare the chosen impact amount (current max, current sum, `_identify_primary`, and the LLM
option) with the gold `impact_amount` for 6 reports, and report exact-match rates.
