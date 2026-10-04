# Deep dive: pattern-based extractors (over- and under-extraction)

Owner: main session.

Status:
- The code analysis of the finding and recommendation extractors is done.
- The metrics against the gold labels are done for all 6 reports.
- For the other Phase 9 extractors (cross-references, annexures, previous-audit references,
  entities, executive-summary index, section classifier), Agent C is building the pattern table.
  It is merged here when it arrives.

## Finding extractor

Code: `enrichment/finding_extractor.py` (1,092 lines, all read) and `semantic_patterns.py`
(489 lines, all read).

### Design as built
- **The unit is a child chunk.** One finding = one `paragraph`/`list` chunk ≥ 50 characters
  (`:747-756`). The finding `text` is the whole chunk.
  - A chunk holding background plus a finding is one finding.
  - A finding split across two chunks becomes two findings, or one if the other half has no
    cue.
  - Table chunks are never findings.
- **The acceptance rule** (`:784-788`) is an OR of three rules:
  1. `confidence >= 0.5`;
  2. has money and (a type pattern or an indicator);
  3. a type pattern and an indicator.
- **Confidence** (`semantic_patterns.py:335-394`) is built as:
  - a pattern score: explicit patterns score 0.3–0.4, implicit 0.15–0.25, capped at 0.7;
  - +0.2 if there is any money;
  - +≤0.15 for context (Ministry, scheme, rule or para references);
  - × a report-type multiplier of 0.9–1.2.

  So "Audit observed" plus an amount gives 0.6, and a paragraph with an amount but no cue gives
  0.0–0.2.

### Over-extraction sources (code)
- **Rule 2 lets almost any paragraph with an amount through.**
  - `FINDING_TYPE_PATTERNS` (`:242-627`, about 280 regexes) includes very generic ones:
    `despite`, `delayed`, `pending`, `short`, `difference .{0,20}(of|ranging)`,
    `did not (provide|ensure|…)`, `(was|were) (deficient|inadequate|insufficient|absent)`,
    `\d+ per cent .{0,30}(less than|below|short of|against)`, `ranged from … to … per cent`.
  - The umbrella keyword list (`:66-81`) includes `excess`, `short`, `pending`, `despite`,
    `led to`, `resulted in`.
- **The money signal is itself noisy** (see `monetary.md`: `rs` inside words, quantities read
  as lakh).
- **Management replies are not excluded.** `NON_FINDING_PATTERNS` (`:202-240`) has no
  `stated|replied|informed (that|in)` rule, which gives P9-13.
- **Duplicates.** Executive-summary copies are flagged (`is_executive_summary`) but kept.
  Cross-finding dedup works on summed amounts (`semantic_enrichment_service.py:780-870`) and
  rarely fires.
- **LLM validation covers only 28% of findings** (`llm_validation.md`).

### Under-extraction sources (code)
- **`NON_FINDING_PATTERNS` look at the first 300 characters and discard the whole chunk.** The
  worst offenders:
  - `during (the)? (FYs)? YYYY-YY to YYYY` and `(for|during) the period (from)? YYYY`. CAG
    findings very often open with the audit period: "During 2018-19 to 2022-23, Audit observed
    that …".
  - `as (depicted|shown|given|detailed) in Table` and `(details are)? (given|shown) in (the
    following)? Table`. Findings routinely end "… as detailed in Table 3.2".
  - `^\s*(Source|Note|Reference)[\s:]*`. This has no word boundary, so "Noted…",
    "References…" and "Sources of revenue…" are all discarded.
  - The magnitude is measured against gold (pending). Test: how many gold findings sit in chunks
    that a non-finding pattern rejects.
- **Only `paragraph` and `list` content types are considered.** A finding the chunker typed as
  `header` (P5.5-01 promotes lead sentences to headers) is lost.
- **Implicit findings with no amount and no cue phrase are dropped.** For example, "INCOIS
  lacked a comprehensive physical access control system": the confidence is 0 and rule 3 needs
  an indicator.
- **Chunk-size effects.** Two findings in one chunk count as one, so recall at paragraph level
  is lower than the chunk count suggests.

### Typing (P9-03 "other" overuse)
- `_detect_finding_type` (`:872-916`) tries the umbrella pattern first. It then iterates the
  type dict **in declaration order** and takes the first type whose regex matches. That biases
  toward `IRREGULAR_EXPENDITURE`, `LOSS_OF_REVENUE` and `WASTEFUL_EXPENDITURE`, which are
  declared first.
- "other" appears when nothing matches. With the generic patterns above, a real deficiency
  phrased differently (lacked, absence, gap, not tested, no backup) falls to "other".
- Recommendation: drop regex typing for accepted findings. Get the type from the LLM verdict,
  which is a single batched call per section (`llm_validation.md` redesign).

### Severity (P9-04)
Severity is computed from the summed amount (`:796-801`, `monetary.md` M9–M10). The type
fallback only runs below the "medium" threshold.

## Recommendation extractor

Code: `enrichment/recommendation_extractor.py` (611 lines, all read). The wiring is at
`semantic_enrichment_service.py:216-266`.

### Strategies and their defects

| Strategy | Code | Defect | Evidence |
|---|---|---|---|
| Structural: all chunks under a parent whose TOC title matches `^recommendations?$` etc., or classified `recommendations` | `:92-101, 253-315` | Anchored patterns miss "Recommendation 2.1" / "Recommendations:" / "Audit Recommendations for …" parents. The section classifier rarely outputs `recommendations` (P9-11) | OD: 15 boxes became parents, yet `structural=0` |
| Numbered: `Recommendation (No.)? N [:–-] text` | `:38-45, 317-344` | `(\d+)` then requires `:`/`-`/`–`, so `Recommendation 2.2 In view…` (x.y numbering, no colon; the CAG standard) never matches. In chunked text, the box label is often a separate header chunk from its body | OD 0 numbered |
| List after cue: `(We\|Audit) recommend(s)? that:\n1. …` in **one** chunk | `:50-54, 346-395` | The chunker splits the cue and each list item into separate chunks. Only arabic `1.` items are handled, not `i.`/`(i)`/`(a)`. The cue must be "We/Audit recommend that", not "The following recommendations were made", "Audit suggests", "It is recommended" | HP_2019 p.19: `i. Income and expenditure … may be shown…` and `ii. Reference to rules may be given…` are separate `paragraph` chunks, lost |
| Verb: first of 4 regexes, **whole chunk** becomes the rec text | `:106-116, 415-495` | See below | |

Verb strategy detail:
- **Pattern 4 over-matches.** `(?:The\s+)?(?:[A-Z]{2,8})\s+(should|may (consider|ensure)|needs? to)`
  is compiled with `re.IGNORECASE` (`:151`), so `[A-Z]{2,8}` matches **any 2–8-letter word**:
  "uniforms should", "schools should", "funds should". This is the main source of false
  positives (OD p.128 `…uniforms should…`).
- **Pattern 3 is too narrow.** The subject list is fixed (Ministry, Department, Government, GoI,
  NHAI, Railways, Board, Corporation, Authority) and the modal list is too:
  `should|may consider|needs to|is required to|must`. It misses:
  - `The Department may take steps`, `may ensure`, `may review`, `may put in place`;
  - subjects such as "State Government", "SMED", "ULBs", "PRIs", "the Company", "MoES",
    "INCOIS".
- **No pattern covers passive advisory forms,** the dominant state/ATIR style: `… may be
  increased / ensured / shown / given / strengthened / considered`, `… should be ensured`,
  `… needs to be …`.
- **Rejection filters discard real recommendations:**
  - Any chunk with "Act|Rules|Manual|as per|in accordance|stipulated|prescribed" in its first
    150 characters is dropped unless it says "Audit recommend". Many recommendations name the
    rule they want enforced.
  - "Audit observed/noticed/found/noted" anywhere in the chunk drops it. Chunks that hold a
    finding and its closing recommendation are lost.
  - "verb-late": a chunk over 200 characters whose verb sits after 40% of the text is dropped.
- **Dedup is too weak.** It compares only the first 80 characters, lowercased (`:193-229`).
  Executive-summary and chapter copies, which are worded differently, survive (OD: 15
  duplicate texts). Shingle dedup runs only against `numbered` recs, which are almost never
  found.
- **The rec text is the whole chunk,** not the recommendation sentence.

Trace evidence (`scratchpad/step2/main/rec_trace.py`, run on the real chunks):

| Report | Candidate chunks | No pattern | should-have | PAC/guideline | rule-words | verb-late | Accepted |
|---|---|---|---|---|---|---|---|
| HP_2022 | 40 | 23 | 6 | 5 | 3 | 3 | 0 |
| HP_2019 | 20 | 13 | 5 | 1 | 1 | 0 | 0 |

The real OD recommendations, all `paragraph` chunks, match no pattern:
- p.14 `2. … the budgetary outlay for school education may be increased appropriately…`;
- p.14 `3. Efficient utilisation of allocated funds may be ensured…`;
- p.15 `17. The Department may take steps to maintain the normative PupilTeacher Ratio…`.

The same three texts appear again at p.35, p.35 and p.107 (chapter copies), which also match
nothing.

### No LLM check
Recommendations are never validated (`llm_validation.md` §1).

## Proposed direction (to be confirmed with metrics)

1. **Candidate generation per paragraph, using the neighbouring chunks as context:**
   - A header or cue chunk ("Recommendation(s) x.y", "The following recommendations/suggestions
     were made", "Audit recommends") marks the following list-item or paragraph chunks as rec
     candidates, until the next header.
   - Add passive advisory modal patterns (`may be <past participle>`, `should be …`,
     `needs to be …`).
   - Case-sensitive acronym detection for subjects.
2. **One LLM pass per section** judges all finding and recommendation candidates (see
   `llm_validation.md`):
   - it returns span-level text, type, impact amount and addressee;
   - it merges executive-summary and chapter duplicates by `rec_number` and similarity.
3. **Remove the prefix filters that silently drop real findings** (period and table-reference
   rules). Let the LLM judge those chunks instead.

## Results against the gold labels (all 6 reports)

Script: `scripts/score_gold.py`. Raw output: `gold_scores.json`.
- **Matching:** a pipeline item matches a gold item if the pages are within 2 of each other and
  the texts share at least three 5-word shingles, or the first 10 words of the gold anchor.
- **Precision** counts matches to any gold item. "Strict" counts only non-borderline items.
- **Recall** is measured over non-borderline gold items. For recommendations, chapter copies
  that duplicate an Executive Summary item are scored through their original.
- **Output versions:** 2025_08 is scored on the post-fix GPU output. 2025_38 is scored on
  pre-fix union output, which loses 12 of its executive-summary items to text loss.

| Report | Tier | Pipeline findings | Gold (core) | Precision (strict) | Recall | Recall ES / chapter / conclusion | LLM-rejected (of which real) | Pipeline recs | Gold recs (unique) | Rec P | Rec R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025_38 | union | 15 | 74 | 0.933 (0.8) | **0.189** | 2/19 / 8/51 / 4/4 | 1 (1) | 11 | 10 | 0.909 | 0.9 |
| 2025_08 | union | 30 | 129 | 0.967 (0.967) | **0.279** | 7/14 / 28/104 / 1/11 | 2 (2) | 21 | 16 | 0.524 | 0.312 |
| OD_2025_05 | state | 68 | 229 | 0.971 (0.912) | **0.328** | 6/18 / 66/173 / 3/38 | 8 (8) | 36 | 25 | 0.833 | 0.6 |
| JH_2025_02 | state | 33 | 110 | 0.97 (0.939) | **0.309** | 3/6 / 30/95 / 1/9 | 13 (10) | 15 | 7 | 0.467 | 1.0 |
| HP_2022 | local | 87 | 129 | 0.943 (0.931) | 0.682 | 6/20 / 2/8 / atir 80/101 | 4 (1) | 0 | 11 | – | **0.0** |
| BR_2024_03 | local | 81 | 228 | 0.951 (0.926) | **0.346** | 6/18 / 71/200 / 2/10 | 5 (4) | 28 | 26 | 0.821 | 0.885 |

### What this changes

**The main finding problem is under-extraction, not over-extraction.**
- Precision is 93–97%, 80–97% strict.
- Recall is 19–35% for union, state and BR. The pipeline finds roughly 1 real finding in 3 to
  5: 314 pipeline findings against 899 core gold findings in 6 reports.
- The ATIR does better (68%) because its findings are short, amount-bearing sentences, which
  suit rule 2.
- **This reverses the working assumption,** and the fix direction changes with it. The
  priority is generating more candidates, not filtering harder.

**Why real findings are missed.** Recall-loss reasons across the 573 missed core items in 6
reports:

| Reason | Count | Share |
|---|---|---|
| The chunk exists as `paragraph`/`list` but fails all 3 acceptance rules (no cue phrase, no type regex, no money) | 475 | 83% |
| Discarded by `NON_FINDING_PATTERNS` (mostly "during/for the period YYYY", "from YYYY-YY to YYYY", "as detailed in Table") | 63 | 11% |
| Accepted, then removed by the LLM validator | 15 | 3% |
| Text not in any chunk (pre-fix 2025_38 executive summary) | 12 | 3% |
| Chunk typed `table_markdown`, `header` or `image_caption` | 8 | 1% |

The missed findings are ordinary audit prose, for example:
- "INCOIS did not carry out any activity relating to SDG 14…";
- "SAIL lacked a structured policy for capital repairs…";
- "Non-reconciliation of balances of cashbook with bank statements.";
- "Funds of ₹1.37 crore remained unspent due to non-commencement of works."

The last one was missed although it has money: "remained unspent" matches no type regex
(the pattern is `funds? remained unspent` and "Funds of ₹1.37 crore remained" breaks it) and
there is no indicator.

**The LLM validator removes real findings.** In 6 reports it removed 33 candidates, and **26
were real** (79%). OD is exact: my re-run gives 76 candidates and 8 rejected, which equals
production's "8 invalid filtered, 68 remaining", and all 8 are real findings. Reading the
rejected texts shows why. They are real findings with wrong regex metadata, and the prompt
asks "is the monetary value correctly associated?":
- "3.51 lakh eligible students were deprived of free uniforms", parsed as ₹0.04 crore;
- "1,318 lakh books", parsed as ₹13.18 crore;
- the RBI cash difference, tagged with ₹86.66 crore instead of ₹40.50 crore.

Only 1 of the 13 JH rejections (an appendix caption) was right. See `llm_validation.md`.

**Precision by stratum and rule.** Every stratum is above 90% precise:
- confidence < 0.5: 81/88 precise;
- confidence 0.5–0.7: 60/61;
- confidence ≥ 0.7: 58/59;
- acceptance rules 1, 2 and 3 are all above 90%.

So the "unchecked < 0.5 group" is not a precision problem in practice. The earlier concern in
`llm_validation.md` §3 is withdrawn for findings.

**Location blind spots.**
- Executive-summary findings: 30/95 found.
- Conclusion / summing-up findings: 11/72 found.

These are the short, cue-less restatements that the RAG layer would most likely surface.

**Recommendations:**
- **Precision is poor where the verb strategy dominates:** 2025_08 52%, JH 47%. The false
  positives are:
  - audit rebuttals ("The reply … needs to be viewed in the light of…");
  - quoted norms ("Paragraphs 5.5.5 … stipulate that all schools should…", "Rule 31 … provides");
  - fiscal commentary ("Borrowed funds should ideally…").
- **Recall fails on specific forms:**
  - HP_2022 ATIR: 0/11 (roman-numeral and "should pay adequate attention" forms);
  - 2025_08: 5/16 (`2) MoES may …`: "N)" numbering is not matched);
  - OD chapter boxes: 15/25 (passive "may be ensured", "The Department may take steps", "may
    strengthen").
- 2025_38 does well (90%) because it uses the exact `Recommendation N:` form.

### Amounts (150 matched pairs where gold has an impact amount)

| Method | Equals gold impact (±1%) |
|---|---|
| `_identify_primary` (dead code today) | 84 (56%) |
| current `monetary_value` = max of amounts | 81 (54%) |
| current `total_amount_inr` = sum | 72 (48%); 54 (36%) are more than 1.5× gold |

None of the regex methods reaches 60%. That supports the LLM-picks-the-impact-span option
in `monetary.md` §7.

## Metrics still to add
- Per-pattern precision is in `gold_scores.json` (`precision_by_pattern`); no single pattern is
  a significant false-positive source, given the ≥ 90% precision.

For each of the 6 gold reports:
- Findings:
  - precision and recall at chunk level and at gold-paragraph level;
  - by confidence stratum (< 0.5, band, ≥ 0.7);
  - by acceptance rule (1, 2 or 3);
  - by the pattern that fired;
  - recall lost to `NON_FINDING_PATTERNS` and to content type.
- Recommendations: precision and recall by strategy, and by the verb pattern index.
- LLM validator: the rejection accuracy on the band.
- Amounts: an impact-amount match rate for each method (see `monetary.md`).
