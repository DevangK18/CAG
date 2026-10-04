# Deep dive: LLM validation of findings and recommendations

Owner: main session. Status: done. Both the code analysis and the measurement against 6 gold
reports are complete (`extractor_precision_recall.md`, `gold_scores.json`).

## How it is supposed to work

Regex over-extracts candidates (high recall). An LLM then reads each candidate and rejects
the ones that are not real findings or recommendations (high precision).

## How it actually works

Code: `semantic_enrichment_service.py:202-206`, `:608-706`, and
`enrichment/llm_validator.py` (all 488 lines read).

1. **Findings only.** There is a recommendation prompt (`llm_validator.py:110-122`), but no
   request builder for it (only `create_finding_validation_request` and
   `create_section_validation_request` exist, `:455-488`) and no call site. The only caller is
   `semantic_enrichment_service.py:674`, for findings. **Recommendations are never
   LLM-validated.** Section validation (`create_section_validation_request`) is dead code too.
2. **Only a confidence band is checked.**
   - `needs_validation` is `0.5 <= confidence < 0.7` (`llm_validator.py:224`; bounds from
     `enrichment_patterns.yaml:333-334`).
   - The service keeps every finding outside the band without an LLM call
     (`semantic_enrichment_service.py:657-660`, comment "High confidence or below threshold -
     keep as-is").
   - The validator's own docstring (`llm_validator.py:131`) says below the band means
     "Rejected by regex", so the two files disagree. The service wins, and the low-confidence
     findings are kept.
3. **Most findings never reach the LLM.** The measurement below comes from
   `scratchpad/step2/main/finding_stats.py`, run over all 26 outputs (post-validation counts):

   | Confidence | Findings | Share | LLM-checked? |
   |------------|----------|-------|--------------|
   | < 0.5 | 559 | 45% | no, kept |
   | 0.5–0.7 | 351 | 28% | yes (survivors) |
   | ≥ 0.7 | 324 | 26% | no, kept |

   **72% of findings are never checked.**
   - The < 0.5 group exists because `finding_extractor.py:784-788` accepts a chunk as a finding
     if **any** of these holds:
     - `confidence >= 0.5`;
     - it has money **and** (a finding-type regex or an indicator matches);
     - a finding-type regex **and** an indicator match.
   - The finding-type regexes are very broad: `despite`, `delayed`, `pending`, `short`,
     `difference .{0,20}(of|ranging)`, `did not (provide|ensure|…)`,
     `\d+ per cent .{0,30}(against|below)`, …
     So almost any paragraph with an amount becomes a finding, at confidence 0.0–0.49, and is
     never checked.
4. **When the LLM does run, it rejects a lot.** Rejection rate inside the band, from run logs:
   - union 2025_20 (?) 29/55;
   - 2025_14 16/26;
   - 2025_26 17/40;
   - JH 13/21;
   - OD 8/32;
   - HP_2022 4/5.

   ~~Roughly 35–50% of mid-confidence findings are false.~~ **Corrected after the gold labels:**
   these rejections are mostly wrong. 79% of LLM-rejected candidates are real findings (see
   "Measured" below), and the < 0.5 group is about 92% precise.
5. **Failures count as "validated".**
   - `validate_single` catches every exception, including a 429 after all retries are
     exhausted, and returns `UNCERTAIN` (`llm_validator.py:270-276`).
   - The service treats anything that is not `INVALID` as valid (`:680-683`), so its own
     `except` (`:685-688`) never fires.
   - Union run 35994256570: 31 findings failed after about 5 minutes of retries each
     (`generate_with_retry`: 8 retries, 5→60 s, `src/core/gemini_client.py:81-123`). All were
     kept and counted as validated:

     | Report | Failed / in band |
     |--------|------------------|
     | 2025_16 | 11/16 |
     | 2023_11 | 6/7 |
     | 2025_18 | 4/4 |
     | 2025_03 | 2/2 |
     | 2024_01 | 2/2 |
     | 2023_20 | 3/30 |
     | 2023_07 | 1/14 |
     | 2023_19 | 1/27 |
     | 2025_14 | 1/26 |

     Each failure costs about 5 minutes of wall time, which accounts for about 2.5 h of union
     Phase 9.
   - The "LLM validation: N invalid …" summary line is logged only when `invalid_count > 0`
     (`:700`), so in reports where every call failed nothing reports it.
6. **The LLM is not shown the finding.**
   - The request carries `chunk_text[:1500]` plus `finding_type`, `monetary_value_crore` and
     `severity` (`llm_validator.py:455-472`, `:334-356`).
   - Because a finding is the whole chunk, the LLM effectively judges "does this chunk contain
     a finding?".
   - Chunks longer than 1,500 characters are cut, so the part that makes it a finding (or not)
     may be missing.
7. **The prompt mixes two questions and biases toward VALID.**
   - The criteria (`:84-88`) ask both whether it is a finding and whether the type and amount
     are right. A real finding with a wrong type can be rejected, which deletes a real finding
     because its label was wrong.
   - "Be conservative - only mark INVALID if clearly wrong" pushes toward keeping false
     positives.
   - `corrected_value` is never populated, so a wrong type is never corrected.
8. **Response parsing is fragile.**
   - `_parse_response` requires the reply to start with `VALID` or `INVALID` (`:364-374`).
     Anything else, such as `**VALID**`, `Verdict: INVALID` or a leading thought, becomes
     UNCERTAIN, which means kept.
   - There is no structured output (JSON schema) and no logging of UNCERTAIN counts.
9. **Refinement data is never collected.**
   - Invalid findings are appended to `logs/pattern_refinement/invalid_extractions_<date>.jsonl`
     (`:382-424`).
   - In the container that is `/app/logs/pattern_refinement`, mounted to the VM's
     `${WORK_DIR}/logs`. The workflow uploads only `logs/traces/` and `logs/*.log`
     (`run-parsing.yml:243-244`), so the JSONL stays on the VM disk and nobody reads it.
10. **Everything runs sequentially.** There is one blocking call per finding (`:661-683`) and no
    batching or concurrency. This is the P9-14 runtime problem (Agent C covers the shared rate
    limiter).
11. **The model is `gemini-3.8-flash`** (`enrichment_patterns.yaml:339`), called through Vertex
    with `get_gemini_client`. No AI Studio key is used, which is correct.

## Knock-on effects

- **Severity and totals.**
  - Every unchecked false finding adds its amounts to `total_amount_inr`, which is summed
    across all amounts in the chunk (`finding_extractor.py:796`).
  - That flows into severity (`:799`), report totals and the summaries ("40 findings with a
    cumulative monetary impact of ₹2,522.78 crore"). See `monetary.md`.
- **Recommendations.** Verb-strategy false positives (e.g. OD p.128 "uniforms should…") are
  never filtered. Pattern analysis is in `extractor_precision_recall.md`.

## First redesign draft (superseded by "Revised recommendation" below)

1. **Candidates stay regex-based and high-recall,** but get their own unit: the paragraph or
   sentence span that matched, not the whole chunk. The span is used as `text`, with the chunk
   kept as context.
2. **The LLM judges every candidate** (findings and recommendations), not a band, with
   separate questions:
   - is it a finding or a recommendation (yes/no, with reason);
   - the corrected type;
   - which amount in the text is the impact amount.
3. **Batch per section.**
   - Send the section text once with the numbered candidate spans, and get a JSON array of
     verdicts back with `response_mime_type=application/json` and a schema.
   - A 150-page report goes from about 40–60 single calls to about 10–20 section calls.
   - Add a thread pool under one shared rate limiter (Agent C's design).
4. **Fail closed but visible.**
   - On a final failure, mark the item `validation_status: "unverified"`. Do not treat it as
     valid.
   - Keep the item, but exclude it from totals and severity until it is re-validated.
   - Log the counts at WARNING in the phase summary.
5. **Add the LLM for recall as well.**
   - For sections that yield no candidates but clearly are audit-observation sections (by
     classification, or by "Audit observed" density), ask the LLM to list the findings and
     recommendations in the section (extraction, not just validation).
   - Its outputs are matched back to spans in the text, so every extracted item stays
     grounded.
   - Whether this is needed depends on the recall numbers from the gold set.
6. **Persist the verdicts in the output:** `validation_status`, `validator_reason`,
   `validator_model`. The pattern-refinement JSONL goes to GCS
   (`gs://…/logs/pattern_refinement/`) so the patterns can be tuned from real data.
7. **Remove the dead code:** the band thresholds, `validate_batch`, the unused section request
   builder and `use_batch_api`. Alternatively, wire up section validation deliberately if the
   P9-11 fix needs it.

## Measured against the gold labels (6 reports)

- **The validator mostly deletes real findings.**
  - Re-running the deterministic extractor without the LLM and diffing against production output
    gives 33 candidates removed by the LLM. **26 of them (79%) are real gold findings.**
  - OD_2025_05 reproduces exactly: 76 candidates, 8 rejected, which equals the production log's
    "8 invalid filtered, 68 remaining". All 8 are real.
  - JH: 10 of 13 rejections are real.
- **Why.** The removed findings carry wrong regex metadata, and prompt criterion 3 ("Is the
  monetary value correctly associated…") turns wrong metadata into INVALID:
  - "3.51 lakh eligible students were deprived of free uniforms", parsed as ₹0.04 crore;
  - "1,318 lakh books", parsed as ₹13.18 crore;
  - the RBI cash difference, tagged ₹86.66 crore instead of ₹40.50 crore;
  - several with `finding_type` "other".
- **The finding set it guards is already about 95% precise.** Every confidence stratum is at
  least 90% precise. §3's worry that unchecked low-confidence findings would be noisy does not
  hold for findings.
- **So in its current form the validator has negative value.** It costs about 2.5 h of union
  Phase 9 wall time and removes more true findings than false ones.

## Revised recommendation

The problem is **recall** (19–35%) and **metadata** (type, impact amount), not precision.
Redirect the LLM accordingly:

1. **Short term:** switch off rejection. Either set `llm_validation.enabled: false` for findings,
   or keep the call but never drop a finding on INVALID; store the verdict only. This is a
   config-only change, and it immediately restores the 3% of recall the validator removes.
2. **Main fix (recall):** per-section LLM extraction.
   - For each audit-chapter section, send the section text once and ask for every finding and
     recommendation as verbatim spans, with type, impact amount (span plus value), addressee
     and recommendation number.
   - Ground each returned span back to the chunk text by exact or fuzzy match, and drop
     anything that doesn't match (no hallucinated items).
   - Keep the regex candidates as a cross-check: a regex hit that the LLM omits is logged, not
     silently dropped.
   - Call volume is about 10–25 calls per report, batched under the shared rate limiter
     (Agent C's P9-14 design).
3. **Metadata:** take the type and impact amount from that same call. `monetary.md` shows the
   best regex impact-amount method matches gold in only 56% of cases.
4. **If a validator is kept at all,** it asks only "is this span an audit finding or
   recommendation (yes/no)", with the span itself in the prompt, JSON output, and fail-visible
   `validation_status`.
5. **Evaluation gate:** before merging, run the new Phase 9 on the 6 gold reports and require
   finding recall ≥ 80% at precision ≥ 90%, recommendation recall ≥ 90%, and impact-amount
   match ≥ 80%. The scorer is `scripts/score_gold.py`.
