# Agent D: Phase 10 (`src/batch_pipeline`)

**Status: COMPLETE (2026-09-26).** Code reviewed: `feature/gcp-migration` @ 782d9d0.
Scratch scripts: `<scratchpad>/step2/D/`, where
`<scratchpad>` = `/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad`.

## Work log

**Files read fully (line count):**
- `batch_service.py` (1471)
- `prompts/summary_variants.py` (1777)
- `prompts/overview_extraction.py` (411)
- `prompts/hierarchical_summaries.py` (129)
- `prompts/chart_extraction.py` (226)
- `prompts/finding_extraction.py` (104)
- `prompts/implicit_finding.py` (99)
- `prompts/entity_extraction.py` (88)
- `prompts/__init__.py` (15)
- `process_results.py` (662)
- `merge_utils.py` (157)
- `phase10_service.py` (119)
- `submit_jobs.py` (274)
- `check_status.py` (562)
- `README.md` (225)
- `__init__.py` (23)
- `enrichment/__init__.py` (33)
- `enrichment/gemini_visual_extractor.py` (977)
- `enrichment/visual_post_processor.py` (687)
- `enrichment/enrichment_service.py` (488)
- `enrichment/enrichment_router.py` (321)
- `enrichment/openai_batch.py` (341)
- `enrichment/chart_extractor.py` (651)

**Also read:**
- Call sites: `src/parsing_pipeline/main.py:186-225` and `main.py:1393-1667` (Phase 10a/10b/10c);
  `src/core/gemini_client.py` (135).
- Related code in other agents' scope, read only to trace inputs:
  - `content_extraction_service.py:520-582`, `:674-819`;
  - `rag_pipeline/indexer.py:299-330`.

**Scripts run** (all read-only, no LLM calls):

| Script | Purpose | Result |
|---|---|---|
| `rebuild_summary_prompt.py` | Rebuild the exact 5 variant prompts for all 25 reports | **State/local prompts contain `<built-in function input>` instead of report data** (P10a-01 root cause). Union prompts contain the full input. |
| `summary_input_quality.py` | What `build_summary_input` feeds the variants | See D-10a-06 |
| `raptor_coverage.py` | Which parents get chapter/section summaries, and how much text each prompt sees | See D-10a-03 and D-10a-04 |
| `phase10_log_stats.py` | Per-run Phase 10 duration and retry, 429, re-request and list-response counts | See D-10b-01 and D-10b-02 |
| `toc_filter_check.py` | Tables that 10c flagged as TOC | 83 flagged, about 62 are real data tables (D-10c-02) |
| `fuzzy_overview_match.py` | Test `find_llm_overview_file` on a missing file | Returns another report's LLM overview (D-10a-05) |

**Ad-hoc checks:**
- Example-number leakage in summaries.
- Summary lengths and endings.
- Placeholder counts.
- Image-chunk hydration status.
- Table skip criteria.

**How each finding was established:**
- Verified by running code: D-10a-01, D-10a-03, D-10a-04, D-10a-05, D-10b-03, D-10c-02.
- Verified from output files and logs: D-10a-02, D-10b-01, D-10b-02, D-10b-04, D-10c-01.
- Verified by reading only: the rest, as marked on each issue.

---

## Phase 10a: overview, summary variants, RAPTOR summaries

### Data flow

1. **Entry.** `main.py:1407-1481` builds `json_files` from `state.enrichment_complete[*].assembled_output_path`,
   which is `data/processed/<tier>/<id>_chunks.json`. It then calls, in this order:
   - `BatchService.submit_overview_batch`
   - `submit_summary_batch`
   - `submit_hierarchical_batch`
   - `create_job_tracker`
   - `process_results.build_final_overviews`
2. **Execution.** Each submit call builds prompts and runs them through `_process_batch_gemini`
   (`batch_service.py:302-354`): a thread pool of 5, then `generate_with_retry`
   (`src/core/gemini_client.py:83-127`, Vertex, 8 retries, about 5 min).
3. **Overview** (`batch_service.py:360-480`).
   - `build_overview_prompt(data)` in `overview_extraction.py:184` uses:
     - the first 60 parents as the TOC;
     - `_get_section_content` for intro/scope, glossary and exec summary.
   - Output: `data/batch_jobs/overviews/<id>_overview_llm.json`.
4. **Summaries** (`batch_service.py:482-644`).
   - `build_summary_input(data)` (`summary_variants.py:180`) is built from:
     - metadata;
     - the top 25 findings by `monetary_value`;
     - 20 recommendations;
     - exec summary text;
     - the first 8 tables;
     - entities.
   - For each of the 5 variants, `get_summary_prompt(variant, input, data)` (`:348-369`) produces the prompt.
   - Output: `data/batch_jobs/summaries/<id>_summaries.json`.
5. **RAPTOR** (`batch_service.py:1133-1317`).
   - "Chapter" is a parent with `hierarchy.level_1` and no `level_2` (`:1441-1445`).
   - "Section" is a parent with `level_2` and no `level_3` (`:1447-1451`).
   - Content is the concatenation of the parent's *direct* children (`:1453-1466`).
   - Model: `gemini-3.5-flash-lite`.
   - Output: `data/batch_jobs/hierarchical/<id>_hierarchical.json`.
6. **Final overview** (`process_results.py:155-232`).
   - `extract_overview_from_json` + `merge_llm_overview_data` (`merge_utils.py:64`).
   - Output: `data/processed/<tier>/<id>_overview.json`.

### Does it run? (evidence)

Yes, in every run. Counts from the logs:

| Run | Overviews | Summaries | Hierarchical |
|---|---|---|---|
| Union | 18/18 | 88/90 | 1256/1256 |
| State | 2/2 | 10/10 | 186/186 |
| Local | 4/4 | 20/20 | 715/715 |
| GPU | 1/1 | 5/5 | 57/57 |

Phase time and 429s:

| Run | Phase 10a time | 429 retries |
|---|---|---|
| Union | ~26 min | 19 |
| State | ~5 min | 2 |
| Local | ~7 min | 6 |
| GPU | ~2 min | 0 |

The Claude path (`USE_CLAUDE_BATCH`) never runs.

### Issues

#### D-10a-01 · critical · State and local summary prompts contain no report data: `{input}` is evaluated inside f-strings
- **Location:**
  - The ten tier prompt builders are f-strings containing `{input}`:
    - `summary_variants.py:449` (executive, state), `:515` (executive, local);
    - `:683` (journalist, state), `:774` (journalist, local);
    - `:969` (deep dive, state), `:1067` (deep dive, local);
    - `:1263` (simple, state), `:1345` (simple, local);
    - `:1550` (policy, state), `:1658` (policy, local).
  - The later `.format(input=...)` is at `summary_variants.py:364-369`.
- **Root cause:**
  - The state and local prompt functions return f-strings so they can interpolate `{state_display}`. Inside an f-string, `{input}` is evaluated immediately as Python's built-in `input` function, so the template text becomes `## Report Data:\n<built-in function input>`.
  - `get_summary_prompt` then calls `.format(input=summary_input, …)`. No `{input}` placeholder is left, so nothing is substituted, and Python raises no error for unused keyword arguments.
  - The model receives only the instructions plus the tier examples: headlines, "₹500 Crore—the annual budget of 50 district hospitals", "₹50 Lakh—the annual budget of 5 Gram Panchayats". It writes a plausible story around those. That explains:
    - OD, a school-education audit, summarised as a hospital-equipment story;
    - the KA summary describing an "ATIR … 30 ZPs, 226 TPs";
    - the JH "₹1,200 Crore … DMF" headline;
    - "the specific department checked is not stated in the report".
  - Union prompts are plain strings (`:384`, `:601`, `:871`, `:1188`, `:1442`), so `.format` works for them.
- **Explains Step 1:** P10a-01 fully, including why the overview and RAPTOR summaries for the same reports are grounded (different code paths) and why union summaries are fine.
- **Evidence:**
  - `step2/D/rebuild_summary_prompt.py` rebuilt all 125 prompts:
    - all 30 state/local prompts have `builtin_leak=True`, `contains_input=False`, and are 2.7–4.9k chars;
    - all 95 union prompts contain the input and are 15–47k chars;
    - the summary input itself was built correctly for state/local (27–36k chars) and then dropped.
  - Tail of the OD journalist prompt: `## Report Data:\n<built-in function input>\n\n## Output: …` (`step2/D/OD_journalist_prompt_tail.txt`).
  - Leaked example numbers found in the state/local outputs:

    | Report | Leaked examples |
    |---|---|
    | KA | "₹50 Lakh", "₹25 Crore", "200 Gram Panchayats", "60%", "5 Gram Panchayats" |
    | HP_2019 | "5 Gram Panchayats", "₹50 Lakh", "60%" |
    | JH | "₹1,200 Crore" |
    | BR | "village community hall", "₹25 Crore" |

- **Why tests missed it:** `tests/batch_pipeline/test_tier_specific_prompts.py` (370 lines) only asserts on template wording ("Chief Secretary", "Gram Panchayat" and so on). No test checks that the report data reaches the prompt.
- **Could union be hit?** Not by this bug. Any future union prompt converted to an f-string (for example, to add a ministry name) would be hit the same way.
- **Fix proposal:**
  1. In the 10 f-strings, change `{input}` to `{{input}}`. Better: stop mixing f-strings and `.format`. Build every template with `string.Template` or `str.replace("{input}", summary_input)`, and pass `state_display` the same way.
  2. Add a hard guard in `submit_summary_batch` (`batch_service.py:516-517`): `if summary_input[:200] not in prompt: raise ValueError(f"summary input missing from {variant} prompt")`.
  3. Add a unit test that loops over tiers × variants and asserts that a sentinel string from `summary_input` is present and `"<built-in function"` is absent.
  4. Regenerate the summaries for the 6 state/local reports (30 calls) and delete the fabricated files in GCS `batch_jobs/summaries/` for those IDs.
- **Risk / effort:** very low regression risk. S.
- **Confidence:** verified by running.

#### D-10a-02 · medium · Summary variants lost to 429s are not retried; a partial file overwrites any earlier complete one
- **Location:**
  - `batch_service.py:294-300`: an exception after the 8 retries in `generate_with_retry` becomes `error`.
  - `:597-644`: `_save_summary_results` writes whatever succeeded and replaces the whole file.
  - `main.py:1466-1480`: the phase is reported complete when `merged > 0`.
- **Root cause:**
  - The about-5-minute retry window is exhausted during busy spells, and there is no second pass over the failed IDs.
  - Every run regenerates all 5 variants. There is no skip of existing variants, so on a rerun a report with a transient failure loses a variant that previously existed.
  - The failure is recorded only in `errors` inside the file. The run still ends "success".
- **Explains Step 1:** P10a-02 (2023_07 `deep_dive`, 2024_13 `journalist`).
- **Evidence:**
  - Union 10a log: `summary complete: 88/90 succeeded`, 19 × 429 retries.
  - `batch_jobs/summaries/2023_07…json` has `errors:[deep_dive 429]`.
- **Fix proposal:**
  - After `_process_batch_gemini`, collect failed requests and retry them once with a longer backoff, sequentially (for example, 2 minutes after the batch).
  - Merge with the existing summaries file instead of overwriting: keep old variants that did not regenerate, and record `stale: true`.
  - Surface the failures in the run status (hand-off to C, P1-03).
- **Risk / effort:** low. S.
- **Confidence:** verified from output and logs.

#### D-10a-03 · high · RAPTOR chapter summaries see only a chapter's opening text, and deeper parents are never summarised
- **Location:**
  - `batch_service.py:1205-1236`: chapter content is `parent_content[chapter_id]`.
  - `:1453-1466`: `_build_parent_content_map` uses direct children only.
  - `:1441-1451`: chapter and section definitions.
  - `hierarchical_summaries.py:37-39, 83-85`: the 12k and 6k character truncation.
- **Root cause:**
  - A chapter parent's direct children are only the text before its first sub-section. All section text hangs off the section parents, so the "chapter summary" summarises the chapter introduction, not the chapter.
  - `_is_section` accepts only `level_2` parents with no `level_3`. Parents at level 3 or deeper (for example 3.2.1) get no summary of any kind, and their text is not covered by any section summary.
- **Evidence** (`raptor_coverage.py`):
  - Share of a chapter's text that the chapter prompt sees: median **~13%**. Examples: 2023_20 4%, 2025_06 5%, 2025_08 6%, HP_2022 1%, BR 1%; at most 48% (2023_11).
  - Share of report text in no hierarchical summary at all: HP_2022 **75%**, 2023_20 46%, OD 41%, JH 37%, 2025_38 37%, 2023_19 35%; typically 20–35%.
- **Explains Step 1:** Not reported by Step 1, which checked the faithfulness of chapter summaries, not their coverage. NEW.
- **Fix proposal:**
  - Build content by `hierarchy.level_1` for chapters, and by the path prefix for sections, aggregating all descendants.
  - Better, go bottom-up (true RAPTOR): summarise leaf parents first, then summarise a chapter from its section summaries plus its direct text. This keeps the prompt under the limit without truncating away 87% of the chapter.
  - Summarise every parent with at least N characters, whatever its depth, or define "section" as the deepest `toc_level ≤ 2` ancestor.
- **Risk / effort:** medium. It changes the RAPTOR output shape and count; the indexer consumes `chapter_summaries` and `section_summaries`. M.
- **Confidence:** verified by running.

#### D-10a-04 · medium · RAPTOR sends duplicate and fragment parents; BR makes 275 duplicate requests
- **Location:** `batch_service.py:1205-1274`. There is no de-duplication by `chunk_id`, and no filter for heading-only or garbage parents. `custom_id` is derived from `chunk_id` (`:1214`, `:1252`), so duplicates also collide in `id_mapping`.
- **Root cause:** RAPTOR trusts `parent_chunks` as given. Phase 7.5's duplicated parents (P7-01) and Phase 5.5's fragment parents (P5.5-01) each become requests.
- **Explains Step 1:** P10a-03.
- **Evidence:** in BR, 639 parents but 329 unique IDs; 493 "chapters"; **275 duplicate requests**. The local run's 10a made 715 hierarchical calls, 525 of them for BR.
- **Fix proposal:**
  - De-duplicate requests by `chunk_id`.
  - Skip parents whose title fails `is_garbage_title` or whose content is below the threshold.
  - The real fix is upstream (P7-01 and P5.5-01, Agents A and B). This is defensive.
- **Risk / effort:** low. S.
- **Confidence:** verified by running.

#### D-10a-05 · high (latent) · The final overview can merge another report's LLM overview (fuzzy file match), or a stale one from an earlier run
- **Location:** `merge_utils.py:16-61`, `find_llm_overview_file`, called from `merge_utils.py:97`. The overview LLM file is written only on success (`batch_service.py:464-480`).
- **Root cause:**
  - If this run's `<id>_overview_llm.json` is missing (Gemini error, or a JSON parse error, which writes only a `.txt`), the lookup falls back to:
    - Strategy 2: prefixes of the report ID down to 4 underscore parts;
    - Strategy 3: the first 2 parts (`"OD_2025"`, `"2025_04"`).
  - For state and local IDs (`{ST}_{year}_{no}_…`), Strategy 3 matches **any report from the same state and year**.
  - Separately, an `_overview_llm.json` from an earlier run is never deleted, so a failed regeneration silently reuses stale scope, objectives, topics and entities.
- **Evidence:** `fuzzy_overview_match.py`:
  - `OD_2025_05_School_Education…` matched `OD_2025_07_Compliance_Audit_on_Irrigation_overview_llm.json`;
  - `2025_04_Some_Other_Report` matched the 2025_04 Union Accounts overview.
- **Explains Step 1:** not triggered in the audited runs (all overviews succeeded). Latent. With hundreds of state reports (for example several `OD_2025_*`), one parse failure contaminates a report's overview with another report's audit scope and entities.
- **Fix proposal:**
  - Exact match only: `overviews_dir / f"{report_id}_overview_llm.json"`.
  - Delete or rename the previous `_overview_llm.json` before regeneration, or check that `generated_at` is newer than the chunks file.
  - Record `llm_extraction_available: false` when it is missing.
- **Risk / effort:** low. S.
- **Confidence:** verified by running.

#### D-10a-06 · medium · The summary input is weak even when it arrives (all tiers)
- **Location:** `summary_variants.py:180-316`.
- **Root cause and evidence** (`summary_input_quality.py`):
  1. **Findings ordering.** The "top 25" findings are ranked by `monetary_value` (`:224-230`). That value is wrong in many cases (P9-05: summed nested amounts, "lakh students" read as rupees), so the most prominent finding in the input is often an artefact.
  2. **The "Amounts cited in findings" line** still passes a summed crore total (`:211`), which the accuracy rules then tell the model not to use.
  3. **"KEY TABLES" is just the first 8 tables in document order** (`:283-296`). In 24 of 25 reports the first table is on p.3–5, which is the contents or abbreviations table. No data tables are chosen for relevance.
  4. **Exec summary.** Matched only through hierarchy titles "executive summary"/"preface" (`:319-335`). It is **0 chars for 2025_08 and KA_2022_06** and 865 chars for HP_2019; there the model gets no narrative text at all.
  5. **Findings text is cut at 600 chars** (`:236`).
  6. **RAPTOR chapter summaries are not used,** though they run in the same phase. The summary batch runs *before* the hierarchical batch (`main.py:1440-1442`).
- **Explains Step 1:** part of the 7–25% ungrounded numbers in *union* summaries (P10a-01's union baseline), together with prompt example leakage (D-10a-07).
- **Fix proposal:**
  - Run hierarchical summaries first, then feed the chapter summaries (after the D-10a-03 fix) plus the overview's `audit_objectives` and `audit_scope` into the summary input.
  - Pick tables that are referenced in the findings, not the first 8.
  - Rank findings by severity and the finding's own stated loss amount, not by `monetary_value`.
  - Drop the summed total line.
- **Risk / effort:** medium. Summary content changes; to be judged on a gold subset. M.
- **Confidence:** verified by running (input measurements); the effect is inferred.

#### D-10a-07 · medium · Summary prompts include concrete example numbers and headlines that leak into the output; there is no grounding check
- **Location:**
  - Union examples: `summary_variants.py:45-49, 612-619, 641, 1211-1213`.
  - State: `:697-701, 722, 1286-1288`.
  - Local: `:790-794, 813-816, 1370-1372`.
  - `TIER_CONTEXT` (`:22-111`) is unused. It is imported by tests only, and its examples are duplicated in the prompts.
- **Root cause:**
  - Prompts show "₹12,000 Crore—enough to build 2,400 government schools", sample headlines and "60% of GPs…". Even with real input, models reuse these.
  - `ACCURACY_RULES` (`:340-345`, added 2026-09-25) forbids summing and placeholders, but it does not say "use only numbers present in the Report Data".
  - Nothing validates the output.
- **Evidence:**
  - Union outputs, which did have input:

    | Report | Leaked example | Variants |
    |---|---|---|
    | 2023_11 | "12 crore families" | journalist, policy |
    | 2024_01 | "60%" | 4 variants |
    | 2025_03 | "60%" | — |
    | 2025_18 | "60%" | — |
    | 2025_14 | "₹1,200 Crore" | journalist |

  - The union summaries predate `ACCURACY_RULES`. They were generated 2026-09-24 19:25 and still contain fill-in placeholders: 2023_07 policy 5, 2024_13 policy 12, 2025_14 policy 9.
  - The post-rules GPU 2025_08 run has 0 placeholders in all 5 variants.
- **Fix proposal:**
  - Replace the numeric examples with non-numeric style guidance, or mark them clearly as fictional.
  - Add "every number you state must appear in Report Data".
  - After generation, extract ₹, % and count numbers from each variant and check them against the summary input plus chunk text (reusing the Step 1 check). Flag or regenerate variants above a threshold.
  - Regenerate the union summaries so they pick up `ACCURACY_RULES`.
- **Risk / effort:** low. S–M.
- **Confidence:** verified from outputs.

#### D-10a-08 · low · The overview prompt only sees the first 60 parents, and keyword-based section selection misses tables
- **Location:**
  - `overview_extraction.py:195` (`[:60]`).
  - `:383-411` (`_get_section_content` keeps only `paragraph/text/header`, matched by hierarchy keywords; "Overview" and "Chapter 1" also match "Chapter 10", "Chapter 11" and so on).
  - Truncation at `:352-361`.
- **Root cause:**
  - With fragmented TOCs (BR 639 parents, HP_2022 286, 2025_06 407), `topics_covered` is built from the first 60 entries, often not past chapter 2.
  - Abbreviation lists are usually tables, so they are not in the glossary input.
- **Evidence:** read only. Not quantified further; Step 1 found overviews grounded.
- **Fix proposal:**
  - Pass only `toc_level ≤ 2` de-duplicated parents (all of them).
  - Include `table_markdown` chunks under glossary or abbreviation headings.
- **Risk / effort:** low. S.
- **Confidence:** verified by reading.

#### D-10a-09 · low · The job tracker and mapping file use different timestamps; `Phase10Service` and the Claude path are broken or dead
- **Location:**
  - `batch_service.py:374-376` auto-generates ts1 for the mapping; `:827-828` `create_job_tracker` makes ts2. The GCS listing shows the result:
    - `job_20260925_232408_mapping.json` vs `job_20260925_233129.json`;
    - `_load_id_mapping` (`:255-261`) falls back to "latest mapping on the same day".
  - `phase10_service.py:38-41` passes `jobs_dir=` to `BatchService`, which has no such argument. `Phase10Service()` raises `TypeError`. It is exported in `__init__.py:21` and unused.
  - README and CLI docstrings reference `services.batch_pipeline` (old path) and Anthropic keys.
- **Root cause:** leftovers from the Claude batch design.
- **Evidence:** read, plus the GCS job file names.
- **Fix proposal:**
  - Delete `Phase10Service`.
  - Create the tracker timestamp first and pass it to all submits.
  - Update or trim the README.
- **Risk / effort:** none. S.
- **Confidence:** verified by reading.

### Improvements (not bugs)
- **Order and dependencies.** Run overview and hierarchical first, then summaries using both (see D-10a-06). All three are independent per report, so run them per report rather than per phase. A report's 10a then finishes as a unit, and failures are per report.
- **Cache.** Skip regenerating variants and overviews whose inputs have not changed (hash the prompt and store it in the output file). Every rerun currently repays about 7 Pro calls per report.
- **Model policy.** The overview and 4 of the 5 variants use `gemini-3.1-pro-preview`, a *preview* model, in production (`batch_service.py:189-196`). CLAUDE.md documents `gemini-3.5-flash` for batch summaries. Decide on the model and document it (see the models section).

### Wired-and-working inventory (10a)

| Component / flag | Status | Evidence |
|---|---|---|
| Overview extraction (Gemini sync) | Works | 25/25 overviews; Step 1 found them grounded |
| Summary variants, union | Runs, weak input / leaked examples (D-10a-06, D-10a-07) | 88/90 |
| Summary variants, state/local | **Runs but broken: no report input** (D-10a-01) | `rebuild_summary_prompt.py` |
| `ACCURACY_RULES` | Works (post 09-25) | GPU 2025_08: 0 placeholders |
| RAPTOR chapter summaries | Runs, covers ~13% of chapter text (D-10a-03) | `raptor_coverage.py` |
| RAPTOR section summaries | Runs; levels ≥3 never summarised | same |
| Final overview merge | Works; fuzzy-match latent bug (D-10a-05) | |
| `summaries_available` flag in overview | Works | |
| Retry of failed variants | Missing (D-10a-02) | |
| Claude batch path (`USE_CLAUDE_BATCH`) | Never runs (dead in production) | env default false |
| `Phase10Service` | Dead and broken (`TypeError`) | `phase10_service.py:38` |
| `submit_jobs` / `check_status` / `process_results` CLIs (Phase 10 mode) | Unused in production; process-results is a no-op for Gemini sync | |
| Job tracker `reports.*` flags | Never updated in the Gemini path (always false / []) | `main.py:1468-1473` |
| `TIER_CONTEXT` dict | Dead (tests only) | |
| `REPORT_SUMMARY_PROMPT` (`hierarchical_summaries.py:121`) | Dead | |

---

## Phase 10b: visual extraction (`gemini_visual_extractor.py`)

### Data flow
1. **Entry.** `main.py:1557-1593` passes `chunk_files` and `pdf_dir="data/raw"` to `submit_visual_extraction_job` (`:537`).
2. **Picking items.** `_identify_extraction_items` (`:650-786`) picks:
   - `table_markdown` chunks not "Gemini-hydrated";
   - `image_caption` / `chart_data_path` chunks whose content is a file path.
3. **Processing.** `process_batch` (`:461-533`) runs a **sequential** `for` loop. Each item goes through `extract_chart` / `extract_table`, then `_generate_json` (up to 3 JSON re-asks), then `generate_with_retry` (8 retries).
4. **Write-back.** `_apply_results_to_jsons` (`:824-919`):
   - sets `structured_data`;
   - replaces `image_caption` content with `description`;
   - rewrites `*_chunks.json` in place.
5. **Check.** `main._validate_phase_10b_completion` (`main.py:1502-1555`) counts chunks still holding paths.

### Does it run? (evidence)

| Run | Items | Tables / charts / multi-page | Succeeded | Time | 429 retries |
|---|---|---|---|---|---|
| Union | 385 | 0 / 385 / 0 | 380 | 116 min | 166 |
| State | 76 | 0 / 76 / 0 | 75 | 92 min | 72 |
| Local | 114 | 0 / 114 / 0 | 114 | 104 min | 36 |
| GPU | 29 | 0 / 29 / 0 | 29 | 14 min | 39 |

The state run also had 4 JSON re-requests, 6 of them from list responses. **Tables: 0 in every run.**

### Issues

#### D-10b-01 · medium (time) · Visual extraction is strictly sequential; 429s dominate the wall time
- **Location:**
  - `gemini_visual_extractor.py:487-531`: a `for … await`, one item at a time.
  - The client-side limiter `:276-292` (120 RPM) is irrelevant, because concurrency is 1.
  - `generate_with_retry` sleeps with `time.sleep` inside `asyncio.to_thread` (`:294-298`).
- **Root cause:** no concurrency. Each 429 blocks the whole phase for 5 to 60 s, and the retry window is about 5 min per item.
- **Explains Step 1:** P10b-01. 10b is the longest single phase after 9: 92–116 min per run, 52% of the state run.
- **Evidence:** per-item wall time is 18 s (union), 73 s (state), 55 s (local), 29 s (GPU).
- **Fix proposal: a shared, bounded-concurrency limiter for all Gemini calls.**
  1. Add `src/core/gemini_limiter.py`:
     - an `asyncio.Semaphore(N)` (N ≈ 8–16) plus a token bucket;
     - on a 429, back off adaptively and globally (AIMD: halve the permitted concurrency and restore slowly);
     - one process-wide instance used by 10a (replacing its `ThreadPoolExecutor(5)`), 10b, and Phase 9's LLM validator (hand-off to the main session).
  2. In `process_batch`: `await asyncio.gather(*(bounded(item) for item in items))`, with per-item exceptions captured and results kept in order.
  3. **Across VMs (X-02).** Vertex Dynamic Shared Quota is per project and model, so the VMs compete with each other. Options:
     - (a) simplest: stagger runs, or give each VM a lower N;
     - (b) a shared token bucket in GCS or Firestore (a lease per minute), which is more complex;
     - (c) move 10b to Vertex **Batch Prediction** (a JSONL of image parts in GCS, async, ~50% cost, no 429s). 10b does not need to be synchronous, since nothing downstream in the same run needs chart values except 10c, which can run later.

     Recommendation: implement (1)+(2) now. Consider (c) for bulk backfills of hundreds of reports.
  4. Use `asyncio.sleep`-based backoff in the async path (an `async` variant of `generate_with_retry`), so waits do not tie up threads.
- **Risk / effort:** medium. Concurrency makes the per-file JSON write-back order irrelevant, since it happens after `gather`. M.
- **Confidence:** verified from logs; the design is a proposal.

#### D-10b-02 · low–medium · Chart results lost to 429s, truncated JSON and list responses
- **Location:**
  - `_generate_json` `:300-315`: re-asks up to 3 times on invalid JSON.
  - `_parse_json_response` `:946-948`: rejects a top-level list.
  - `max_output_tokens=8192` `:354-355, 398-399`.
  - Exceptions after retries: `:359-361, 402-404`.
- **Root cause:**
  - A JSON list (`[{…}]`) is treated as invalid, which wastes a call.
  - When all attempts fail, the item is dropped. It is not queued for a later pass, and its chunk keeps a file path as content (see D-10b-04).
  - `response_mime_type="application/json"` is set, but no `response_schema` is set, so shape drift (lists, wrapper keys) is possible.
- **Explains Step 1:** P10b-02. The union run lost 5 items and the state run 1. The state run had 6 list responses.
- **Evidence:** log counts above.
- **Fix proposal:**
  - Unwrap single-element lists (`if isinstance(parsed, list) and len(parsed)==1 and isinstance(parsed[0], dict)`).
  - Pass `response_schema` for charts and tables.
  - Run a final retry pass over failed items after the main pass.
  - Record failures in the chunk (`structured_data={"extraction_error":…}`) and give the chunk a caption-derived text instead of a path.
- **Risk / effort:** low. S.
- **Confidence:** verified from logs and reading.

#### D-10b-03 · medium · Every image, including photos, banners and failed-table crops, goes to the *chart* prompt: the subtype filter reads a key that never exists
- **Location:**
  - `gemini_visual_extractor.py:749-754`: `visual_subtype = chunk.get("visual_subtype", "")`, then skip unless it is in `("chart","data_visualization","")`.
  - Phase 6 stores the subtype at `structured_data.visual_subtype` (`content_extraction_service.py:816`); there is no top-level field.
- **Root cause:**
  - The top-level `visual_subtype` is `None` for **all 628 image chunks in 25 reports**, so the filter always passes.
  - Photos (`photo`), maps, flowcharts and `table_as_image` all get `CHART_EXTRACTION_PROMPT`.
  - Tier-3 table crops, where pdfplumber and Docling both failed (`content_extraction_service.py:529-546`), are saved as `image_caption` with `label="Table"`, which classifies as `unknown`. So they are extracted as *charts*: series and data_points instead of a markdown table, and the "table" is replaced by a one-sentence description.
  - After hydration, `structured_data` is overwritten by the Gemini result (`:875`), which erases the Phase 6 `visual_subtype`.
- **Explains Step 1:**
  - P6-07 (10b side): BR has ~86 of 103 images as photos/banners; 336 of 598 hydrated images have no series.
  - Part of P6-05: table data from Tier-3 is stored as chart series.
- **Evidence:**
  - Script counts: top-level `visual_subtype` is None in 628/628.
  - Hydrated with no series: 336 (BR 89, 2025_20 36, OD 23).
- **Fix proposal:**
  - Read `structured_data.visual_subtype`.
  - Route `table_as_image` and `layout_label=="Table"` crops to `extract_table` (the table prompt, then 10c table hydration).
  - Skip `photo` (keep a short generic caption only).
  - Send `map`, `flowchart` and `diagram` to a description-only prompt (cheaper, no series).
  - Preserve `visual_subtype` when writing results (merge rather than replace).
  - Hand-off to B: Phase 6 should label Tier-3 table crops explicitly (for example `visual_subtype="table_as_image"`) and use a block type other than "picture".
- **Risk / effort:** low–medium. S–M.
- **Confidence:** verified by running (counts) and reading.

#### D-10b-04 · medium · Skipped or failed images keep a local file path as chunk text, and the hydration check contradicts the skip rule
- **Location:**
  - `:756-758`: `_is_non_data_image` skips signature-sized and cover-page images but leaves them untouched.
  - `:884-892`: when there is no description, the content stays a path.
  - `main.py:1502-1555`: `_validate_phase_10b_completion` then flags exactly these intentionally skipped chunks as "not hydrated".
- **Root cause:**
  - Nothing replaces or drops a chunk whose image was deliberately skipped, or whose extraction failed. The chunk content `data/extraction_images/charts/<id>_picture_p3_….png` stays in the child chunks and will be embedded and indexed.
- **Explains Step 1:** P6-06. There are 62 chunks with path content:

  | Report | Chunks with path content |
  |---|---|
  | BR | 5 |
  | HP_2019 | 4 |
  | HP_2022 | 4 |
  | JH | 5 |
  | KA | 7 |
  | OD | 6 |
  | GPU 2025_08 | 3 |
  | 2025_06 (stale, P1-04) | 23 |
  | Others | a few |

  The P1-14a warnings in every run ("5 / 11 / 20 / 3 image_caption chunks still have file paths") are these same chunks.
- **Evidence:** script counts, matched against the log lines "skipped N signature/emblem/icon images".
- **Fix proposal:**
  - For skipped non-data images, mark `structured_data={"skipped":"non_data"}` and set content to an empty or short caption. Better, have Phase 6 or 8 drop them (hand-off to B/C).
  - On failure, set content to the surrounding caption or title text, never a path.
  - Make `_validate_phase_10b_completion` ignore intentionally skipped images and count real failures.
  - The indexer should also reject path-like content (RAG deferred; note only).
- **Risk / effort:** low. S.
- **Confidence:** verified from outputs.

#### D-10b-05 · medium · Tier-3 table re-extraction never runs; the table branch is dead and would over-fire if revived
- **Location:**
  - `:690-720`: the table branch skips any table with `"rows" in structured_data`.
  - `:680-682`: `pdf_path = data/raw/<source_filename>`, but PDFs live in `data/raw/<tier>/`.
- **Root cause:**
  - Phase 6 gives *every* table a StructuredTable with `rows` (1,095/1,095 tables), so every table counts as "Gemini hydrated" and is skipped. Hence `Tables: 0` in all runs.
  - If that check were fixed, the path bug would silently skip every table, because the PDF is not found.
  - If both were fixed, every table (about 45 per report) would be re-extracted by Gemini, since there is no quality criterion.
  - Multi-page table items (`MULTI_PAGE_TABLE_PROMPT`, `extract_multi_page_table`) are never created: dead code.
- **Explains Step 1:** P10c-01 (tables hydrated 0) at its source, and why Tier-3 table failures come out as chart descriptions (see D-10b-03).
- **Evidence:** logs show `Tables: 0` in 4/4 runs. Script: `with_rows == tables` in 25/25 reports.
- **Fix proposal:**
  - Decide explicitly which tables go to Gemini. For example, those with a Phase 6 quality flag (split cells, `extraction_confidence < x`, a column-count mismatch, reversed text) plus Tier-3 crops.
  - Resolve the PDF via `data/raw/<tier>/` or the manifest path.
  - Either implement multi-page groups from `multi_page_table_handler` output, or delete the dead code.
- **Risk / effort:** medium (cost and time if the selection is too broad). M.
- **Confidence:** verified from logs and outputs.

#### D-10b-06 · low · The recorded model and method name is wrong
- **Location:** `:878, :880`; `visual_post_processor.py:450, :540`. Every chunk says `gemini-2.5-flash-vision`, but the model is `gemini-3.8-flash` (`:228`).
- **Fix:** write `self.model`.
- **Effort:** S. **Confidence:** reading.

### Wired-and-working inventory (10b)

| Component / flag | Status | Evidence |
|---|---|---|
| Chart extraction (`extract_chart`) | Works, sequential; wrong items sent (D-10b-03) | 598/660 images hydrated |
| Table extraction (`extract_table`) | **Never runs** (D-10b-05) | `Tables: 0` × 4 |
| Multi-page table extraction | **Dead code** | never enqueued |
| Non-data image skip | Works, but leaves path content (D-10b-04) | log "skipped N" |
| `visual_subtype` filter | **Broken: reads a missing key** | 628/628 None |
| `pdf_dir` resolution | **Broken** (`data/raw` vs `data/raw/<tier>`); unused only because the image path already exists | `main.py:1583` |
| RPM limiter | Irrelevant (concurrency 1) | |
| JSON re-ask | Works; list responses not unwrapped | 6 in state run |
| `phase_10b_complete` flag | Set when ≥1 update | |
| `_validate_phase_10b_completion` | Runs; false alarms (D-10b-04) | |

---

## Phase 10c: visual post-processing (`visual_post_processor.py`)

### Data flow
`main.py:1618-1667` calls `process_all(chunk_files)`. `process_file` (`:156-273`) then handles each chunk:
- **For each table:**
  1. TOC filter (`:277-330`).
  2. Title inference (`:334-401`), stored in `structured_data.title`.
  3. Hydration if `structured_data.markdown` exists without `rows` (`:216-228`).
  4. Confidence score, which overwrites `extraction_confidence` (`:231-232`).
- **For each image with `series`:** `_hydrate_chart` builds a StructuredChart (`:460-559`).

The file is then rewritten.

### Does it run? (evidence)

| Run | Tables processed | TOC-filtered | Tables hydrated | Charts hydrated | Titles enriched |
|---|---|---|---|---|---|
| Union | 457 | 25 | **0** | 178 | 414 |
| State | 213 | 15 | **0** | 50 | 193 |
| Local | 350 | 38 | **0** | 18 | 312 |
| GPU | 40 | 4 | **0** | 16 | 31 |

### Issues

#### D-10c-01 · low–medium · Table hydration is dead, and "titles enriched" never reach searchable text or captions
- **Location:** `:216-228` (needs Gemini `markdown` with no `rows`, which never happens because of D-10b-05) and `:206-213` (title written only to `structured_data.title`).
- **Root cause:**
  - Hydration is unreachable.
  - The inferred title is:
    - the first "Table X" line above the table;
    - else any paragraph or header under 200 chars within 50 pt above it (often a running header or the last sentence of a paragraph);
    - else the deepest hierarchy title.
  - The title is stored where neither the chunk `content` nor the Phase 8 caption fields see it.
- **Explains Step 1:** P10c-01. Also contributes to P6-04 (generic or wrong table captions), because 10c's better "Table 3.2: …" matches never replace the Phase 6 caption.
- **Evidence:** logs (hydrated 0 × 4); reading.
- **Fix proposal:**
  - When a "Table/Statement/Chart N.N" caption is found, write it to the chunk's caption and title fields and prepend it to `content`. This helps the embeddings.
  - Do not use the loose "short paragraph above" fallback without the regex.
  - Let hydration follow the D-10b-05 decision.
- **Risk / effort:** low. S.
- **Confidence:** verified from logs and reading.

#### D-10c-02 · medium · The TOC filter flags about 75% false positives among real data tables, and overwrites Phase 8 confidence for every table
- **Location:** `visual_post_processor.py:277-330`, with two heuristics at fault:
  - "last column mostly 1–3 digit integers" (`:315-328`);
  - header contains "page" plus "no" or "#" (`:311-313`).
  - Also `:197-203` and `:231-232`.
- **Root cause:**
  - Counts, sample sizes and small integers in the last column are common in CAG data tables ("No. of GPs", "Percentage", "Excess claim").
  - Flagged tables get `extraction_confidence=0.05` and `_filtered_reason="toc_detected"`, and skip title inference.
  - Every other table's Phase 8 `extraction_confidence` is overwritten by the 10c heuristic score.
- **Evidence:** `toc_filter_check.py`:
  - 83 flagged; ~62 are clearly data tables, for example:
    - BR p48 staff vacancies, p55 UCs pending;
    - OD p34 fund utilisation;
    - HP p23 budget vs actual;
    - JH p42 revenue heads;
    - 2023_11 p130–139 hospital occupancy.
  - The genuine TOCs (p3–5) are mostly caught by the "page" header rule.
  - Nothing downstream reads `extraction_confidence` or `_filtered_reason` today (grep: only assembly writes it; the API model exposes it). The impact is latent, but becomes real the moment the indexer or API filters on confidence.
- **Explains Step 1:** NEW.
- **Fix proposal:**
  - TOC detection only on pages within the front matter (before the first chapter page), *and* a last column that is monotonically non-decreasing page numbers ≤ the page count, *and* a first column of section-like numbering.
  - Better: reuse the Phase 4 printed-TOC page range (Agent A) and simply drop table chunks on those pages in Phase 6/8.
  - Do not overwrite `extraction_confidence`; write `postprocess_confidence` separately.
- **Risk / effort:** low. S.
- **Confidence:** verified by running.

#### D-10c-03 · medium · Chart values never reach the searchable text; `image_path` stores the description
- **Location:**
  - `gemini_visual_extractor.py:884-889`: content becomes `description` only.
  - `visual_post_processor.py:523`: `image_path=chunk.get("content")`, which by then is the description, not the path.
- **Root cause:**
  - The values sit only in `structured_data.series[].data_points`. Queries like "what was X in 2021-22" cannot hit them through the embeddings or BM25.
  - The image path is lost after 10b, so the StructuredChart `image_path` is the description sentence.
- **Explains Step 1:** P6-05.
- **Evidence:** read, matching Step 1 samples (JH, OD, GPU, KA).
- **Fix proposal:**
  - In 10b or 10c, set content to: title, description, then a compact linearised table of series × category values (for example `2019-20: 1,234; 2020-21: …`). Keep the image path in `structured_data.image_path` before overwriting the content.
  - Cap the linearised block (for example 1,500 chars).
- **Risk / effort:** low. S.
- **Confidence:** verified by reading.

### Wired-and-working inventory (10c)

| Component | Status | Evidence |
|---|---|---|
| TOC filtering | Runs, ~75% false positives (D-10c-02) | script |
| Title enrichment | Runs, result invisible (D-10c-01) | |
| Table hydration | **Never fires** | 0 × 4 runs |
| Chart hydration (StructuredChart) | Works; `image_path` wrong (D-10c-03) | 262 charts with series |
| Confidence scoring | Runs; overwrites Phase 8 value | |

---

## LLM finding and entity extraction in `batch_pipeline`: does it run?

**Answer for the main session's findings and recommendations deep dive: no. No LLM finding, implicit-finding, entity or recommendation extraction runs in production. Nothing from `batch_pipeline` is merged into Phase 9's `semantic_enrichment.findings`.** Phase 9's regex findings (plus the narrow LLM validation band) are the only findings.

**Evidence:**

1. `EnrichmentService` (`enrichment/enrichment_service.py`), which uses `prompts/finding_extraction.py`, `implicit_finding.py` and `entity_extraction.py`:
   - It is reachable only through the CLI flags `submit_jobs --enrichment`, `check_status --enrichment` and `process_results --enrichment`. No call from `main.py` or `parallel_runner.py` (grep).
   - It **cannot even start**. `__init__` instantiates `AnthropicBatchService` (`enrichment_service.py:84`), which is never defined or imported; the file imports `BatchService as GeminiBatchService` (`:35`) and never uses it. The result is a `NameError`.
   - Its providers are **OpenAI** (`openai_batch.py`, `OPENAI_API_KEY`, `gpt-4o-mini`) and **Anthropic** (`claude-sonnet-5`), not Vertex. That violates the "all AI calls via Vertex" rule if revived.
   - Its results would go to `data/batch_jobs/enrichment/<id>_enrichment.json` (`:443-455`). There is no merge step into `*_chunks.json`.
   - Custom IDs are `report_id[:30]_chunk_id[:20]` (`:179`), which collide across reports sharing a 30-char prefix.
   - The router skips any chunk that already has a regex finding (`enrichment_router.py:165-177`), so it could never correct regex over-extraction. It only adds.
2. `ChartExtractorService` (`enrichment/chart_extractor.py`, Claude Vision) is CLI-only too. It targets `content_type=="chart_data_path"`, which no chunk has (0 in 25 reports). It would also crash:
   - `prompts/chart_extraction.py:232` calls `.format(context=…)` on a template with single-brace JSON (`:13-68`), raising `KeyError`/`ValueError`;
   - `process_chart_results` calls `results_response.text` on an iterator (`chart_extractor.py:311`).
3. The only LLM calls in Phase 10 are overview, summaries, RAPTOR, and 10b chart and image extraction (all Vertex, `src/core/gemini_client.py`, `vertexai=True`).

**Implication for the deep dive:** the design space is open. If the regex extractors are turned into candidate generators with an LLM judge, that should be built fresh on `gemini_client` plus the shared limiter (D-10b-01). Reuse the prompt wording in `prompts/finding_extraction.py` if useful, not `EnrichmentService`. Recommendation: delete `EnrichmentService`, `EnrichmentRouter`, `openai_batch.py`, `ChartExtractorService` and `prompts/chart_extraction.py` (hand-off D-X-01).

---

## Models, endpoints, retries, JSON robustness, cost tracking

### Endpoint
- All production Phase 10 calls go through `get_gemini_client()`, which uses `genai.Client(vertexai=True, location="global")` with ADC (`gemini_client.py:26-72`). **No AI Studio key path exists.** Compliant.
- Non-Vertex code exists only in the dead paths:
  - Anthropic: `batch_service` Claude mode, `chart_extractor`, `enrichment_service`;
  - OpenAI: `openai_batch`.

### Models vs CLAUDE.md

| Component | Code | CLAUDE.md |
|---|---|---|
| Overview | `gemini-3.1-pro-preview` (`batch_service.py:190`) | — |
| Summaries: executive, journalist, deep_dive, policy | `gemini-3.1-pro-preview` | "Batch Summaries: `gemini-3.5-flash`" |
| Summaries: simple | `gemini-3.8-flash` | same |
| RAPTOR | `gemini-3.5-flash-lite` (`:1173`) | not listed |
| 10b | `gemini-3.8-flash` (`gemini_visual_extractor.py:228`) | not listed |

- **D-M-01 · low:** the documentation and the code disagree, and a **preview** model is used for 5 of the 6 generation calls per report. Decide and document. Prefer a GA Pro model, or Flash with grounding checks.

### Retries
- `generate_with_retry`: 8 retries at 5, 10, 20, 40, then 60 s ×4 (±20%), about 5 min.
- It is transient-only, and it treats "Empty response" as transient.
- `MAX_TOKENS` with no text is correctly non-retried.
- `MAX_TOKENS` *with* partial text is returned as success, silently truncated (`gemini_client.py:110-118`). **D-M-02 · low:** check `finish_reason` and flag truncation.
  - No truncation was observed: 0/2,214 hierarchical summaries empty, 7 without terminal punctuation, and variant endings look complete.
  - Summaries have large budgets (12k–24k), but Gemini 3.x thinking tokens count against `max_output_tokens`. RAPTOR's 500/200-token budgets are the risk if a thinking model is ever configured.
- The retries are blocking `time.sleep`, even in the async 10b path (`asyncio.to_thread`). Fine at concurrency 1, wasteful once parallel (see D-10b-01).
- There are **no request timeouts** on `generate_content`. A hung call blocks the phase indefinitely, bounded only by the workflow's `max_hours`. **D-M-03 · low:** pass `http_options=types.HttpOptions(timeout=…)`.

### JSON robustness
- The overview uses `clean_json_response` (`process_results.py:44-70`): fence stripping plus a greedy `\{[\s\S]*\}`, with no `response_mime_type`.
  - A parse failure saves `.txt` only, and the merge may then pick a wrong file (D-10a-05).
  - **Fix:** set `response_mime_type="application/json"` and a `response_schema` for the overview.
- 10b: see D-10b-02.

### Cost tracking
**D-M-04 · medium:** Phase 10 records no token usage or cost at all.
- No `usage_metadata` is read anywhere in `src/batch_pipeline` or `gemini_client.py` (grep).
- The job tracker lists no counts or cost, and `src/observability` cost tracking is not wired in.
- With Pro-preview summaries (about 5 × 30–47k input tokens per report) plus about 50–500 RAPTOR calls and 20–100 vision calls per report, per-report cost is unknown.
- **Fix:** have `generate_with_retry` return, or log, `response.usage_metadata`, and aggregate it per phase and per report into the trace or tracker.

---

## Step 1 issue coverage

| Step 1 ID | Explained by | Notes |
|---|---|---|
| P10a-01 (critical) | **D-10a-01** (root cause, verified), D-10a-07 | f-string `{input}` evaluated as the builtin |
| P10a-02 | D-10a-02 | |
| P10a-03 | D-10a-04 (+ upstream P7-01 / P5.5-01) | Also found D-10a-03: chapter summaries see ~13% of the chapter |
| P10b-01 | D-10b-01 | Design for parallel execution plus a shared limiter |
| P10b-02 | D-10b-02 | |
| P10c-01 | D-10c-01, D-10b-05 | Tables never reach 10b, so hydration is unreachable |
| P6-05 (10b/10c side) | D-10c-03, D-10b-03 | |
| P6-06 | D-10b-04 | |
| P6-07 (10b side) | D-10b-03 | Subtype filter reads the wrong key |
| X-02 | D-10b-01 (3) | Options a/b/c; Vertex Batch Prediction suggested for bulk runs |
| P1-03 (10a/10b part) | D-10a-02; hand-off C | Phase 10 failures never change run status |
| P1-04 (10b side) | D-10b-04 | 2025_06 stale 23 path chunks |
| P8-02 "parent summaries never merged back" | Partly: RAPTOR output stays in `batch_jobs/hierarchical/` and nothing writes it to parents or the overview; hand-off C | See hand-offs |

---

## Hand-offs

- **Agent B:**
  - `content_extraction_service.py:529-546, 767-819`: Tier-3 table crops are saved as `image_caption` with `block_type="picture"` and subtype `unknown`. Label them `table_as_image` so 10b can route them to the table prompt (D-10b-03).
  - Also B: `_extract_and_save_visual` writes images to the relative `data/extraction_images/charts`. Fine on the VM.
  - Also B: consider dropping signature-sized and cover images at Phase 6 instead of creating chunks (D-10b-04).
- **Agent B / A:** duplicate and fragment parents (P7-01, P5.5-01) inflate RAPTOR calls (D-10a-04). The front-matter page range from Phase 4 should mark TOC tables (D-10c-02).
- **Agent C:**
  - `main.py:1466-1481` and `:1587`: Phase 10a is marked complete if ≥1 overview merged, and 10b is always "complete". Summary or visual failures never reach the run status or exit code (P1-03).
  - `main.py:1583` passes `pdf_dir="data/raw"`, but PDFs are under `data/raw/<tier>/` (D-10b-05).
  - P8-02: hierarchical summaries are never attached to `parent_chunks[].summary` or the overview.
- **Main session (deep dives):**
  - Answer on LLM finding extraction: see the section above (no; the design space is open).
  - The shared Gemini limiter (D-10b-01) should also serve Phase 9's `_validate_findings_with_llm`.
  - The summary input ranks findings by `monetary_value`, so P9-05 errors surface in every summary (D-10a-06).
- **RAG, deferred (note only):**
  - `rag_pipeline/indexer.py:299-315` globs `*_hierarchical.json` under `--input-dir` (documented as `data/processed`), but the files are written to `data/batch_jobs/hierarchical/`. With the documented command, RAPTOR summaries are never indexed.
  - The indexer should also reject path-like chunk content (D-10b-04).
- **D-X-01 · low (cleanup, D's own scope):** delete the dead and broken modules:
  - `phase10_service.py`, `enrichment/enrichment_service.py`, `enrichment_router.py`, `openai_batch.py`, `chart_extractor.py`;
  - `prompts/chart_extraction.py`, `finding_extraction.py`, `implicit_finding.py`, `entity_extraction.py`;
  - the enrichment and chart-extraction modes in `submit_jobs.py`, `check_status.py` and `process_results.py`;
  - the Claude batch mode, if Vertex-only is policy.

  That is about 3,000 lines. Also update `src/batch_pipeline/README.md`, which describes Anthropic setup and `services/` paths.

---

## Summary (ranked issue list)

| ID | Severity | Title | Location |
|---|---|---|---|
| D-10a-01 | **critical** | State/local summary prompts contain `<built-in function input>` instead of report data (f-string `{input}`) | `summary_variants.py:449,515,683,774,969,1067,1263,1345,1550,1658`; `:364-369` |
| D-10a-03 | high | RAPTOR chapter summaries see ~13% (median) of chapter text; level ≥3 parents never summarised (up to 75% of report text uncovered) | `batch_service.py:1205-1274, 1441-1466` |
| D-10a-05 | high (latent) | Final overview can merge another report's (same state and year) or a stale LLM overview via fuzzy file matching | `merge_utils.py:16-61, 97` |
| D-10b-03 | medium | All images, including photos, maps and failed-table crops, go to the chart prompt: the subtype filter reads a nonexistent top-level key | `gemini_visual_extractor.py:749-754, 875` |
| D-10b-01 | medium | 10b strictly sequential, 429-bound (92–116 min/run); needs a shared bounded-concurrency limiter (and cross-VM strategy) | `gemini_visual_extractor.py:487-531`; `gemini_client.py:83-127` |
| D-10a-06 | medium | Summary input weak: findings ranked by a wrong `monetary_value`, first-8 tables = contents tables, exec summary missing, RAPTOR not used | `summary_variants.py:180-335`; `main.py:1440-1442` |
| D-10a-07 | medium | Prompt example numbers/headlines leak; no "numbers must come from the data" rule or grounding check; union summaries predate `ACCURACY_RULES` | `summary_variants.py` examples; `:340-345` |
| D-10b-04 | medium | Skipped/failed images keep a local file path as chunk text (62 chunks); completeness check false alarms | `gemini_visual_extractor.py:756-758, 884-892`; `main.py:1502-1555` |
| D-10b-05 | medium | Tier-3 table re-extraction never runs (every table has `rows`; wrong `pdf_dir`); multi-page path dead | `gemini_visual_extractor.py:680-720`; `main.py:1583` |
| D-10c-02 | medium | TOC filter: ~62/83 flagged tables are real data tables; overwrites Phase 8 confidence | `visual_post_processor.py:277-330, 197-203, 231-232` |
| D-10c-03 | medium | Chart values not in searchable text; StructuredChart `image_path` holds the description | `gemini_visual_extractor.py:884-889`; `visual_post_processor.py:523` |
| D-10a-02 | medium | Failed summary variants never retried; partial file replaces any complete one; run still "success" | `batch_service.py:294-300, 597-644` |
| D-M-04 | medium | No token or cost tracking anywhere in Phase 10 | `gemini_client.py`, `batch_service.py` |
| D-10a-04 | medium | RAPTOR sends duplicate/fragment parents (BR 275 duplicate requests) | `batch_service.py:1205-1274` |
| D-10c-01 | low–medium | Table hydration dead; inferred titles stored where no caption or search text uses them | `visual_post_processor.py:206-228` |
| D-10b-02 | low–medium | Lost chart results: list responses not unwrapped, no final retry pass, no `response_schema` | `gemini_visual_extractor.py:300-315, 946-948` |
| D-10a-08 | low | Overview prompt sees only the first 60 parents; glossary tables excluded | `overview_extraction.py:195, 383-411` |
| D-M-01 | low | Models disagree with CLAUDE.md; preview Pro model used for 5/6 generation calls | `batch_service.py:189-196` |
| D-M-02 | low | `MAX_TOKENS` with partial text returned as success | `gemini_client.py:110-118` |
| D-M-03 | low | No request timeout on `generate_content` | `gemini_client.py:107` |
| D-10b-06 | low | Chunks record `gemini-2.5-flash-vision` though the model is `gemini-3.8-flash` | `gemini_visual_extractor.py:878-880` |
| D-10a-09 | low | Tracker/mapping timestamp mismatch; `Phase10Service` raises `TypeError`; stale README | `batch_service.py:374-376, 827`; `phase10_service.py:38` |
| D-X-01 | low | ~3k lines of dead or broken non-Vertex enrichment/chart code to delete | `enrichment/*`, `prompts/*`, CLIs |

**Not verified:**
- No Gemini calls were made. The fabricated-summary cause is proven by rebuilding the exact prompt text, not by re-generating.
- The quantitative effect of D-10a-06 and D-10a-07 on union summary accuracy after a fix is not measured.
- The Vertex Batch Prediction option (D-10b-01 (3)) has not been tried for image inputs on this project.
