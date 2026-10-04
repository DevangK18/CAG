# Parsing Pipeline Review: Analysis and Go-Ahead Recommendations

**Date:** 2026-10-04
**Read in full:** `README`, `AGENT_BRIEF`, `step1_findings`, `scorecard`, `pre_audit_review_list`, `step3_fix_list`, the three deep dives (`llm_validation`, `monetary`, `extractor_precision_recall`), `gold_scores.json`, and agent reports A, B, C, D. `step1_metrics.json` was checked for shape only; its numbers are the scorecard.
**Limit:** I read the review, not the code or the outputs. Where I disagree with the plan it is on reasoning and sequencing, not on re-measured facts.

---

## 1. Bottom line

The review is good work and its main conclusions hold. Approve the start, with a narrower first pull request and a changed order for two later ones.

What it establishes:

1. **Text extraction is sound; almost everything built on top of it is not.** Post-fix word recall is 0.97 to 0.99. The damage is in structure (TOC, parents), in Phase 9 (findings, recommendations, money, links) and in Phase 10 (summaries).
2. **Two defects put wrong content in front of users today:** all five summary variants for the six state and local reports are invented, and Bihar's hierarchy is destroyed.
3. **Findings extraction is precise but finds about one finding in three.** This overturns the assumption the pipeline was designed on, and it is the largest piece of work in the plan.
4. **Runs cannot be trusted to report their own failures.** Every run exits 0, and deleted GCS files come back.

The plan's weak points are sequencing (extraction fixes are scheduled after the structure work that depends on them), the size of "PR 1", no prototype behind the Phase 9 redesign, and nothing about what happens downstream in Qdrant, the entity graph and the API once the output schema changes.

---

## 2. How far to trust the review

**Strong.** Agents owned disjoint files, read them completely, and reproduced the worst bugs by running code: the Bihar hierarchy was rebuilt to the exact output (639 parents, 329 unique IDs, 1,645 children under "Corporation"), all 125 summary prompts were rebuilt to show the missing input, and parent assignment was re-simulated to 100% agreement with the output before alternatives were tested. One claim per agent was independently spot-checked. The review also corrected itself twice (the "318 failed calls" figure, and the early belief that findings were over-extracted).

**Caveats that matter for decisions:**

| Caveat | Why it matters |
|---|---|
| The "hand-labelled" answer key was labelled by agents (5 of 6 reports), with adjudication only where pipeline and gold disagreed | The recall conclusion survives (sampled misses were about 90% real), but this key becomes the merge gate for the Phase 9 redesign. Six reports used for both prompt design and gating will overfit |
| 18 of 19 union outputs predate the 09-25 fixes | Union structure numbers (wrong parents 50 to 87%) are not the current baseline. Only one union report (2025_08, GPU) reflects current code |
| No Gemini call was made during the review | The three LLM designs (Phase 9 extraction, Phase 5.7 reviewer, batch prediction) are proposals with no measured result |
| The VM disk was not inspected | The sync bug is read from the workflow file. Very likely right, not observed |
| 26 reports, of which 2 state and 4 local | The TOC parser fixes are fitted to five state and local layouts. A corpus of hundreds will bring layouts nobody has seen |
| The scanned-PDF path has no output at all | CG_2025_01 died at OCR. Everything after OCR on a scanned report is unaudited |

---

## 3. What the review found

### 3.1 Works

- Text and number extraction after the 09-25 fixes; no block fails extraction (all loss is in the garbage filter).
- Overview extraction: grounded in all 25 reports.
- Union summaries: mostly grounded (GPU run 3.8% of numbers not in the PDF).
- Chart values on vector charts: accurate (JH 298/335), though not searchable.
- Findings precision: about 95%, above 90% in every confidence band.
- All production LLM calls go through Vertex with service credentials.

### 3.2 Critical (user-visible now)

| Defect | Cause | Size of fix |
|---|---|---|
| Bihar: 310 duplicate parents, 96% of children under a fake section | Phase 7.5 scans children by page range instead of membership, with IDs that ignore the enclosing parent. Fires on any flat TOC | Small for the safe subset |

### 3.3 The five themes

**Findings and recommendations (Phase 9).** 314 pipeline findings against 899 labelled ones: precision 95%, recall 19 to 35% (68% on the ATIR). 83% of misses are ordinary audit prose with no cue phrase; 11% are thrown away by "non-finding" prefix rules that match how CAG findings normally open ("During 2018-19 to 2022-23, Audit observed..."). The LLM validator removed 33 findings, 26 of them real, while costing about 2.5 hours per union run. Recommendations: 59 of 95 found; 0 of 11 on the ATIR; precision 47 to 52% where the verb strategy dominates, because an acronym pattern compiled case-insensitive matches any short word.

**Money.** "₹1.5 lakh crore" is read as ₹1.5 lakh; quantities ("24.53 lakh candidates") are read as rupees; a finding's total is the sum of every amount in its chunk, and severity follows that sum (JH: 29 of 33 findings "critical"). Fields named `_inr` hold paise, and the entity graph divides as if they were rupees, so every entity amount is 100 times too large. The best regex method picks the right impact amount 56% of the time.

**Document structure.** The TOC quality score measures shape, so the worst TOCs score 100 and no safeguard ever triggers. Consequences: PDF-merger bookmarks ("Binder1.pdf", "Blank Page") win over a good printed contents page; the contents parser mangles the three-column layout every state and local report uses; Phase 5.5 promotes recommendation boxes and sentences to headings; children attach to the wrong section in 10 to 57% of cases because heading positions are matched by title with no page check. Agent B's simulation shows reading-order assignment cuts that to roughly 0 to 7%.

**Extraction fidelity.** Docling's footnote, caption and list labels are discarded, which is the single root of generic table captions, unlinked footnotes and tiny orphan chunks. The garbage filter deletes real content: 148 "(₹ in crore)" unit lines, 81 source lines, about 80 real section headings, and occasionally a whole table. 129 pages of sideways text in five reports come out reversed.

**Run integrity.** Exit code is always 0. A failed report keeps its old output and the indexer ingests it. The built-in "RAG readiness" score rated the worst file in the corpus 92.9 "WORLD-CLASS". Files deleted from GCS are re-uploaded from the VM's disk on the next run.

### 3.4 The pattern underneath

Three habits explain most of the 165 issues, and they are worth more than any single fix:

1. **Failure reported as success.** OCR failure prints a check mark; a failed validation call counts as "validated"; lost summary variants end in "FULL PIPELINE COMPLETE".
2. **Built but never wired.** About eighteen components exist in code and in the guides but never execute in production: Phase 5.7, Tier-3 table re-extraction, table hydration, multi-page Gemini tables, footnote handling, recommendation validation, report-type profiles for ATIR and state, most of `enrichment_patterns.yaml`, the impact-amount logic, red flags, the evidence linker (structurally zero), and more.
3. **Gates that measure shape, not content.** The TOC score, the readiness score, and tests that assert prompt wording.

So the fix that scales to hundreds of reports is monitoring (real exit codes, red flags in the output, content-aware scores), more than any individual heuristic.

---

## 4. Ignore

---

## 5. Assessment of the plan

### 5.1 What is right

- Fixing the two critical bugs, the validator and run integrity first.
- Treating Phase 9 as a redesign, with a measurable gate.
- A shared Gemini limiter before adding more LLM calls.
- Dead code last.
- Checking every pull request against the gold set and the Step 1 scripts.

### 5.2 What I would change

**A. Trim PR 1.** It is described as small but carries about 15 items, including two medium ones that reach outside the parsing pipeline: sharding `manifest.json` (the API reads it) and rewriting the readiness score. Keep PR 1 to changes that are small and self-contained:

| Keep in PR 1 | Move out |
|---|---|
| f-string fix, sentinel test, prompt guard | Manifest sharding (goes with its API change) |
| Validator off | Readiness-score rewrite (verification tooling) |
| Phase 7.5: membership scoping, global dedup, safety valve, runner flag | Phase 7.5 level and page-range rework (with structure) |
| Exit codes, `run_summary.json`, `skip_phases` | |
| Sync fix, both workflows | |
| Stale output quarantine; indexer honours manifest status | |
| Scaffolding logger one-liner; per-run log name | |
| Red flags written to output | |
| **Add:** entity-graph paise fix (one line, live product bug) | |
| **Add:** token and cost logging in `gemini_client` (currently in PR 5) | |

Cost logging belongs first because nobody knows what a run costs today, and every later re-run should report it.

**B. Move the label and filter fixes ahead of the structure work.** The plan puts extraction fidelity (PR 4) after document structure (PR 3). But the structure fix assigns children by walking header chunks in reading order, and the garbage filter currently deletes about 80 real section headings and chapter titles as "duplicates" or "too short". Agent A's heading test for Phase 5.5 also needs Docling's labels. Agent B's own order puts these second. Pull three items forward into PR 3 or before it: keep Docling labels, exempt headings, captions, unit lines and tables from the filter, and normalise padded table markdown.

**C. Split PR 3.** It changes page mapping, the contents parser, source selection, the quality score, Phase 5.5 admission and parent assignment at once. If wrong-parent rates move, nobody will know which change did it. Agent A's dependency order gives a natural split: (a) page map, parser, source selection, score; (b) Phase 5.5 admission and dedup; (c) reading-order parent assignment.

**D. Prototype the Phase 9 redesign before building it.** The gate (recall 80%, precision 90%, recommendations 90%, amounts 80%) is a target with no evidence it is reachable. A spike on two gold reports costs a few dozen calls and answers three questions: is the target realistic, which model is needed, and what it costs per report.

**E. Change how Phase 9 grounds its output.** The plan asks the model for verbatim spans, then fuzzy-matches them back to chunk text. That will fight whitespace, rupee glyphs, hyphenation and glued footnote markers. Simpler: number every paragraph chunk in the section and have the model return chunk numbers with type, amount and a short anchor phrase. Provenance (page, bounding box, chunk ID) then comes for free, IDs stay stable between runs, and nothing can be hallucinated. Allow more than one item per chunk for paragraphs holding two findings.

**F. Hold out part of the answer key.** Use four reports for design and keep two unseen for the gate, or label two or three more. Spot-check 30 to 50 labels yourself; you know these reports better than the labelling agents did.

**G. Decide the "or" items now.** Several fixes read "redesign or delete". Defaults I would set: delete Phase 5.7 (revisit only if the structure metrics still need it), delete the `--workers` path (the GPU makes Docling 1.3 minutes per report, and tiers run on separate VMs), delete the Claude batch path and the non-Vertex enrichment code.

**H. Cheap interim recall.** Only the small regex changes are worth doing before the redesign: remove the period and table-reference prefix rules (63 of 573 misses), exclude management replies, and make the acronym pattern case-sensitive. Skip the medium-sized pattern work unless the redesign slips.

### 5.3 Missing from the plan

1. **Downstream impact.** Renaming `total_amount_inr`, adding `footnote` and `list` content types, and changing logical pages all alter the output schema. The Qdrant payload, the entity-graph indexer, API models and the frontend read these. Ask for a consumer inventory before PR 2, and add "re-index Qdrant and rebuild the entity graph" to the re-run step.
2. **Which page number citations show.** RAG citations use physical page plus one, which is right for PDF navigation but not what is printed on the page. Fixing `source_page_logical` gives you the printed number; whether to display it is a product choice.
3. **What counts as one finding.** Roughly a fifth of labelled findings are executive-summary or conclusion restatements. If the redesign reaches 80% recall, counts triple. Totals, severity distribution and the Findings tab need restatements linked, not double-counted. Put that in the gate.
4. **A wider smoke sample before the bulk run.** One report from each of eight to ten further states, checked only by automatic checks and red flags. No labels needed.
5. **The scanned path.** After the OCR timeout fix, CG_2025_01 needs its own audit.
6. **Workflow test.** Agent C notes the exit-code change may make the shell script skip the upload step. Run one deliberately failing single-report job and confirm partial output still reaches GCS.
7. **Branch.** The review covered `feature/gcp-migration` at 782d9d0, and the GPU workflow lives on `main` and `feature/gpu-vm`. Confirm which branch the seven pull requests target.

---

## 6. The decisions

| # | Claude Code asks | My view |
|---|---|---|
| D1 | Rebuild Phase 9 around per-section LLM extraction | **Yes to the direction**, on four conditions: spike first (5.2 D), chunk-number grounding (5.2 E), a held-out test set (5.2 F), and restatements linked (5.3 item 3). Fix temperature at 0 and record model and prompt version so re-runs are comparable |
| D2 | Stop the validator deleting findings | **Yes, and simply disable it.** The plan keeps the calls and stores verdicts; nothing will read them, and it keeps the 2.5 hours and the spend |
| D3 | Workflow changes | **Yes**, after seeing the diff and after the failing-run test (5.3 item 6). Prefer wiping the VM data directory at run start over `rsync -d`: the VM also keeps `batch_jobs/` from old runs, which is not synced down at all, and two VMs with different local state is the underlying problem |
| D4 | Re-run union after PRs 1 to 3 | **Change the timing.** Regenerate the 30 state and local summaries straight after PR 1 (minutes). Do the full union re-run once, after the Phase 9 work, followed by re-index. A run after PR 3 would have its findings and summaries redone anyway. If union is in front of users now and you want the 09-25 text fixes live sooner, do an interim run after PR 1 with 10a skipped. Clear old visual-extraction results first, since 10b skips anything already present |
| D5 | GCS cleanup | **Wait for PR 1**, then clean GCS once |
| D6 | Manifest fixes | **Do them.** Adding Department and Audit Category columns for state and local is cheaper and more reliable than inferring them |


---

## 7. Suggested reply to Claude Code

```
Approved to start, with changes.

Decisions
- D1: Yes in direction. Before building: (a) spike per-section extraction on 2 gold
  reports and report recall, precision, amount match, model used and tokens;
  (b) ground by numbered chunk IDs plus a short anchor, not verbatim-span fuzzy
  matching; (c) hold out 2 gold reports from prompt design and gate on those;
  (d) link exec-summary and conclusion restatements so totals count unique findings;
  (e) temperature 0, record model and prompt version in the output.
- D2: Yes. Disable the validator outright (enabled: false). Do not keep the calls.
- D3: Yes after I see the diff. Prefer wiping ${WORK_DIR}/data at run start over
  rsync -d. Prove with one deliberately failing single-report run that partial
  output still uploads and the status is non-success. Mirror in the GPU workflow.
- D4: Regenerate the 30 state/local summaries right after PR 1. Full union re-run
  once, after WP-9A, then re-index Qdrant and rebuild the entity graph. Clear old
  visual_extraction results before that run.
- D5: I will clean GCS after PR 1 lands.
- D6: I will fix the manifests, including Department and Audit Category columns.

PR 1 scope (trimmed)
- Keep: f-string fix + sentinel test + prompt guard; validator off; Phase 7.5
  membership scoping, global dedup, safety valve, same flags in both runners;
  exit codes + run_summary.json; skip_phases; sync fix; stale output quarantine
  and indexer honouring manifest status; scaffolding logger; per-run log name;
  red flags written to processing_stats.
- Add: entity graph paise fix (mention_indexer.py:257); token and cost logging in
  gemini_client.
- Move out: manifest sharding (with its API change), readiness-score rewrite,
  Phase 7.5 level and page-range rework (to WP-S).

Order changes
- Bring B-5-01, B-6-16 and B-6-04 (Docling labels, filter exemptions, table
  markdown normalisation) ahead of or into the structure PR. Reading-order parent
  assignment needs the heading chunks the filter currently drops.
- Split the structure PR in three: (a) page map, contents parser, source selection,
  content-aware score; (b) Phase 5.5 admission and dedup; (c) reading-order parent
  assignment. Report wrong-parent, empty-parent and duplicate-chapter counts
  after each.
- Interim Phase 9 regex work: only remove the period/table-reference NON_FINDING
  prefixes, exclude management replies, and make the acronym pattern case-sensitive.

Defaults for "or delete" items: delete Phase 5.7, the --workers path, the Claude
batch path and the non-Vertex enrichment code.

Before PR 2, list every consumer of total_amount_inr / normalized_inr, of
content_type, and of source_page_logical across rag_pipeline, entity_graph, api
and frontend.

Also: grep summary_variants.py for "1 crore = 100 lakhs = 1 million" and fix it.
Confirm which branch these PRs target.
```
