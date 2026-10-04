# Agent B: Phases 5–7.5 (layout, content extraction, tables, chunking, hierarchy)

Status: COMPLETE (2026-09-27).

Scratch folder: `<scratchpad>/step2/B/`. `<scratchpad>` is
`/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad`.

## Work log

- **Read fully:**
  - `hierarchy_enricher.py` (907)
  - `chunking_service.py` (1022)
  - `multi_page_table_handler.py` (765)
  - `content_extraction_service.py` (1171)
  - `chunk_filter_service.py` (190)
  - `src/core/data_contracts.py:145-260`: `ParentChunk` and `ChildChunk`
- **Read in part:**
  - `main.py:1052-1155`: the Phase 7.5 driver
  - `parallel_runner.py:150-300`: the per-report worker, Phases 4–9
  - `toc_reconciliation_service.py:640-670`: Agent A's file, read only to trace P7-02
- **Scripts run (all in `step2/B/`):**
  - `repro_p7_01.py`: rebuilds BR's state before Phase 7.5 from the output (the first 58 parents, and the children re-assigned with the Phase 7 algorithm), then re-runs `HierarchyEnricher`. It reproduces the output **exactly**: 639 parents, 329 unique IDs, 268 duplicated IDs (up to ×5), 1,645 children with `level_1 = "Corporation"`, and 611 children outside their parent's pages. **Verified by running.**
  - `wrong_parent.py` / `wrong_parent2.py`: measure which numbered header children sit under a parent whose title does not carry the same section number (the number is taken from anywhere in the title), and classify why.
  - `sim_assign.py`: re-runs `ChunkingService._find_best_parent_for_page` on the output parents and children. It reproduces the output's parent assignment for **100% of children** in all 11 reports tried. It then compares two alternatives: `start_y` re-derived from the heading on the same page, and reading-order anchor assignment. **Verified by running.**

- **Also read fully:**
  - `layout_analysis_service.py` (380)
  - `text_extractor.py` (295)
  - `text_repair.py` (252)
  - `pdfplumber_table_extractor.py` (559)
  - `structured_table_extractor.py` (853)
  - `enrichment/contextual_caption_service.py` (348)
  - `pdfmux_router.py`: structure plus `extract_table` (`:121-262`); the rest is dead because it is disabled
  - `main.py:564-600`, `:669-700`, `:848-1050` (the Phase 5/6/7 drivers)
  - `assembly_service.py:205-232`, `:625-640` (stats, for the P7-05 hand-off)
  - `visual_post_processor.py:180-225` (10c title, for the hand-off)
  - `parsing_config.yaml`: layout, content_extraction, chunking
  - `_archived_v1`: not imported anywhere (grep), so it was skipped.
- **More scripts (all in `step2/B/`):**
  - `docling_labels.py`: Docling with the pipeline's options on GPU 2025_08 pp.19–22; compares class names with `item.label`. Verified B-5-01 and B-5-02.
  - `p145.py`: Docling on 2025_08 p.145 plus the pipeline's own `ChunkFilterService` and `StructuredTableExtractor`. Verified B-6-04 and B-6-10.
  - `trace_harness.py`, `run_traces.sh`, `summarize_traces.py`: the real Phase 5 and Phase 6 services on 8 PDFs, with a per-block route and filter verdict (appendix).
  - `rotated_text.py`, `rotated_fix_demo.py`: the vertical-text scan of all 26 PDFs, and the demonstrated fix (B-6-05).
  - `chart_text.py`: text inside Docling pictures (B-6-18).
  - `multi_prov.py`: multi-provenance count (B-5-03).
  - Inline scans:
    - rupee font (B-6-06);
    - year-range hyphen joins (B-6-07);
    - superscript footnote markers (B-6-19);
    - header-row statistics over the 26 outputs (B-6-09);
    - layout label and confidence distribution over the 26 outputs (B-5-01, B-5-02).

## Phase 7: Chunking (`chunking_service.py`)

### Data flow
1. `chunk_document` (`:67`) starts from `task.extracted_content`, which is Phase 6 output already cleaned by the garbage filter.
2. `_merge_multi_page_tables` (`:204`) uses the `MultiPageTableHandler`. Tables whose `structured_data` parses are merged into groups; other items pass through, and the result is re-sorted by (page, y0).
3. `_split_oversized_content` (`:360`) splits tables into row groups and text at sentence ends.
4. `_create_parent_chunks` (`:480`) makes one parent per `scaffold["toc"]` entry `[level, title, page]`:
   - The end page comes from the next entry at the same or a higher level (`:541-563`).
   - `start_y_position` comes from `scaffold["heading_positions"]["{page}_{title[:30]}"]` (`:580`).
   - Hierarchy is built by walking the TOC backwards (`:977`).
5. `_create_child_chunks` (`:645`) takes each extracted item in list order and calls `_find_best_parent_for_page` (`:780`), which works as follows:
   - It collects every parent whose page range contains the page.
   - Among parents that **start on that page and have a `start_y`**, it picks the last one whose y is at or above the content (10 pt tolerance).
   - Otherwise it takes the deepest `toc_level`, then the smallest range, then the closest start.
   - Children inherit the parent's hierarchy dict.

### Does it run? (evidence)
Yes, for every report. The log shows `Chunking complete … N parents, M children`, and `sim_assign.py` reproduces the output assignments exactly.

### Issues

#### B-7-01 · high · Parent assignment trusts `start_y_position` values copied from a different page
- **Location:**
  - `chunking_service.py:580` (y lookup), `:821-868` (y filter), `:872-882` (deepest-level tiebreak);
  - the root of the bad y values is in Agent A's file: `toc_reconciliation_service.py:649-668`.
- **Root cause, in two parts:**
  1. Phase 5.5's `_update_heading_positions` matches each Docling header to the **first** TOC entry whose title is ≥0.65 similar (`SequenceMatcher`). It **doesn't check that the header is on the TOC entry's page**, and it writes that header's y under the TOC entry's key.
     - Section numbers barely change the similarity, so a later header with the same name on another page overwrites the y: "3.4 Financial profile" (p.36) vs "1.4 Financial profile" scores 0.95.
     - CAG state and local reports repeat section names (the PRI chapter and the ULB chapter share every name), and union reports repeat "Introduction", "Conclusion" and "Recommendations" in each chapter.
     - Examples, HP_2019 (TOC entry → y it got, and where that y came from):

       | TOC entry | y it got | Copied from |
       |---|---|---|
       | "1.2 Audit mandate", p.13 | 292.05 | "3.2 Audit mandate", p.35 |
       | "1.4 Financial profile", p.15 | 476.15 | "3.4 Financial profile", p.36 |
       | "Chapter-1", p.11 | 61.55 | "CHAPTER-4", p.43 |

     - Where the y is not overwritten it is exact (GPU 2025_08, OD: `start_y` equals the child header's `bbox[1]`), so the two sources use the same top-left coordinate system. The errors come from the wrong matches, not from coordinate systems.
  2. In `_find_best_parent_for_page`, when several sections start on a page:
     - Only those **with** a y take part in the y filter (`:827-832`).
     - A section starting on the page **without** a y loses to the deepest-level parent from the previous page (`:861-864`, `:879`). An L3 "1.3.2" (pp.14–15) beats the L2 "1.4" that starts on p.15.
     - The same happens when the y filter finds nothing, so the result depends on `toc_level` rather than on position.
- **Explains Step 1:** P7-02, and part of P7-03 (heading-only parents: the real section's content goes elsewhere).
- **Evidence** (`wrong_parent.py`, `wrong_parent2.py`, `sim_assign.py`):
  - The simulation reproduces 100% of output assignments.
  - Numbered header chunks under a parent that doesn't carry their number, counting only headers where some parent does carry it:

    | Report | Current | y re-derived on same page | Reading-order anchors |
    |---|---|---|---|
    | HP_2019 | 42/74 (56.8%) | 0 | 0 |
    | HP_2022 | 54/102 (52.9%) | 0 | 0 |
    | JH | 26/108 (24.1%) | 7 | 7 |
    | OD | 10/99 (10.1%) | 1 | 2 |
    | KA | 9/67 (13.4%) | 0 | 1 |
    | GPU 2025_08 | 14/88 (15.9%) | 0 | 0 |
    | 2023_19 (pre-fix) | 54/177 (30.5%) | 3 | 11 |
    | 2025_04 (pre-fix) | 63/76 (82.9%) | 58 | 1 |
    | 2025_16 (pre-fix) | 67/77 (87.0%) | 65 | 0 |
    | 2020_16 (pre-fix) | 11/66 (16.7%) | 2 | 2 |

  - Step 1's lower percentages (HP_2019 35%, JH 14%) counted only numbers at the start of the parent title. Printed-TOC titles carry the number at the end ("Audit objectives 1.2"), and JH's "no parent with that number" cases are mostly this artefact.
  - In the pre-fix 2025_04 and 2025_16, the TOC pages themselves are off by +1 (headers for "1.1…2.6" sit one page before `page_range_physical[0]`; this is Agent A's P4 page offset). So y re-derived on the same page can't help there, and only anchors fix it.
  - Caveat: the simulation scores header children. The anchor method uses those same headers as the signal, so the score is optimistic for body paragraphs, though body paragraphs follow their header in reading order.
- **Fix proposal:**
  - **(a), preferred: reading-order anchor assignment in Phase 7.**
    1. Walk `extracted_content` in reading order (page, y0).
    2. When a `header` item matches a TOC entry that starts within ±1 page (normalised title similarity ≥0.8, or equal section number), switch the current parent to that entry.
    3. Every other item goes to the current parent.
    4. Use the current page-range logic only as a fallback when no anchor has been seen, e.g. before the first heading.

    This makes y coordinates unnecessary, is immune to TOC page offsets, and gives a correct `start_y_position` as a by-product.
  - **(b), and hand-off to Agent A:** `_update_heading_positions` must restrict matches to headers on the TOC entry's page (±1), prefer an exact section-number match, and never overwrite a key that already has a same-page match.
  - **(c):** in `_find_best_parent_for_page`, a parent that starts on this page but has no y should beat a parent carried over from the previous page for content below the page's first heading. At minimum, do not rank by `-toc_level` across different start pages.
- **Risk / effort:**
  - (a) is M: about 60 lines, and it replaces `_build_page_parent_index` usage. The risk is headers that don't match any TOC entry (Docling headers not in the TOC); those correctly stay with the current parent.
  - Regression test: rerun `sim_assign.py` on all 26 outputs.
- **Confidence:** verified by running.

#### B-7-02 · medium · Parent page ranges assume the TOC is sorted by page, and overlap freely
- **Location:** `chunking_service.py:541-567`; the same logic is repeated in `_build_section_page_ranges`, `:183-200`.
- **Root cause:**
  - The end page is taken from the next TOC entry of the same or a higher level in **list order**.
  - The TOC is often not in page order after Phase 5.5 appends entries. BR has appendix L2s (p.167–213) before "Corporation" (p.5–214) and more appendix entries after it; 2025_04 has "2.6 Expenditure" [31,37] before "2.5.3" [31,31].
  - When the next entry's page is earlier than this entry's start, `end_page = max(start, next-1) = start`, or it runs to `max_page` if nothing follows. So ranges are one page, or the whole document, or they overlap arbitrarily.
  - When both entries have a y, ranges overlap on purpose (`:557-559`), which is only safe if the y values are right (B-7-01).
- **Explains Step 1:** feeds P7-01 (BR's "Corporation" [5,214] overlaps everything) and P7-02.
- **Unused guard:** `chunking.max_parent_chunk_pages: 100` (`parsing_config.yaml:222`, `config.py:355`) is defined but **never read**. It would have rejected BR's "Corporation" [5,214].
- **Evidence:** BR's pre-7.5 parents, in `repro_p7_01.py` output: "Formation of various Committees 1.4" is [21,26] while "Organisational setup of PRIs 1.2" is [22,22], and "Corporation" is [5,214].
- **Fix proposal:**
  - Sort the TOC by (page, y, original index) before computing ranges.
  - Compute each end as (next entry of the same or a higher level **in page order**) − 1, or that entry's page when both are on the same page.
  - Reject entries whose range would exceed the enclosing parent's range.
  - With (a) from B-7-01, ranges become informational only: derive them after assignment from the actual child pages (min/max).
- **Risk / effort:** S. **Confidence:** verified by reading, plus the BR data.

#### B-7-03 · medium · `ParentChunk` built without the tier and category fields, so parents are always "compliance"
- **Location:**
  - `chunking_service.py:582-595` (from TOC) and `:629-641` (fallback): `audit_category`, `department` and `report_subtype` are not passed.
  - `data_contracts.py:185-188`: the default is `"compliance"`.
- **Root cause:** parents take the model default. Children do get `audit_category` from `initial_metadata` (`:742`), but that also falls back to `"compliance"` when Phase 1 didn't set it.
- **Explains Step 1:** the root of P8-01 (Agent C owns Phase 8, so this is a hand-off). "Parents are always compliance": 13/26 reports.
- **Fix proposal:** pass `audit_category`, `department` and `report_subtype` from `task.initial_metadata` into both `ParentChunk(...)` calls, exactly as the children do.
- **Risk / effort:** S. **Confidence:** verified by reading (the output has `audit_category: "compliance"` on every parent of OD, a performance audit).

#### B-7-04 · low–medium · Split tables repeat a data row as a "header", and pages of a merged table become 1-row fragments
- **Location:**
  - `chunking_service.py:386-419` (`_split_table`): `headers = [r for r in table.rows if r.row_type == "header"]`, repeated in every piece.
  - `multi_page_table_handler.py:632-639`: rows of later fragments are appended unless the header repeats.
- **Root cause, in two parts:**
  1. `row_type == "header"` comes from `StructuredTableExtractor` row classification. When the first **data** row is classified as a header (e.g. `1. | Nor | Nirmand | Kullu | 0.39`), `_split_table` repeats it in every part.
  2. After a merge, a continuation page whose repeated header row wasn't recognised as a repeat (`_has_repeated_header` needs `num_header_rows > 0` on both and 80% cell match, `:509-529`) contributes its header **as data**. The splitter's budget grouping then leaves a tail group with a single row plus "Total" (HP_2022 part 3 on p.111: header, the repeated row and `Total 42.67`).
- **Explains Step 1:** P6-03.
- **Fix proposal:**
  - Before splitting, treat as header only the **leading** contiguous `header` rows (`rows[:k]` with `k = table.num_header_rows`). Any later row whose cells equal the header row should be dropped as a repeated page header.
  - Merge a final group under about 3 rows into the previous piece when the combined size is within `max_child_chars * 1.1`.
  - Keep the "Total" row with the rows it totals.
- **Risk / effort:** S. **Confidence:** verified by reading, with output evidence from Step 1. Row classification itself is in `structured_table_extractor` (next section).

#### B-7-05 · low · Captions, source lines and unit lines are separate tiny children
- **Location:** `chunking_service.py:678-745`: one child per extracted item, with no joining. `chunk_filter_service._merge_short_runs` (`:90-130`) joins only runs of 2 or more **consecutive** short **paragraphs** on one page.
- **Root cause:** there is no rule that attaches:
  - `Table x.y: …` or `Chart x.y: …` captions to the next table or figure;
  - `(Source: …)`, `(₹ in crore)` and `(Figures represent percentage)` lines to the previous one.
- **Explains Step 1:** P7-04, and part of P6-04 (the real caption exists but is a separate paragraph).
- **Fix proposal:** in Phase 6, after reading order is final, fold:
  - a caption-like paragraph (`TABLE_TITLE_RE`, which already exists at `chunking_service.py:33`) immediately followed by a table or image into that item's `structured_data.title` and a `content` prefix;
  - a following `^\(?(Source|Note)s?\s*:` or unit line into the table's `footnotes` and `content` suffix.

  This also fixes the table titles in P6-04 at the source.
- **Risk / effort:** S–M. **Confidence:** verified by reading.

### Chunking design review (improvements, not bugs)
- **Parent and child boundaries come only from the TOC.** A parent is a TOC entry. Children are Phase 6 blocks, one per Docling element (a paragraph, a table or table piece, an image), assigned by page and y.
  - Parents therefore inherit every TOC defect: Phase 5.5 heading promotion (Agent A) gives empty or heading-only parents, a flat printed TOC triggers 7.5, and a page offset gives wrong parents.
  - Reading-order anchor assignment (B-7-01 (a)) makes the parents follow the **headings actually found in the text**, so TOC page and y errors stop mattering.
  - After assignment, parents with 0 children should be dropped or merged into their neighbour, with their title kept in the hierarchy. Today only "artifact" titles are dropped (Agent C, P2-19).
- **Size limits.**
  - Children are capped at `max_child_chunk_chars: 4000` (`_split_oversized_content`). Tables split by rows with the header repeated; text splits at sentence ends.
  - **There is no minimum size and no overlap**: every short paragraph, caption or list item is its own child (median child length is small; see Step 1, P7-04).
  - For the retriever, merging consecutive small same-parent text blocks up to about 1,000–1,500 characters would cut the child count by roughly 40–50% and improve embedding quality. Keep tables and headers as their own chunks.
  - Parent chunks carry no text (`content_summary` is filled later by Phase 10a). The retriever expands a child to its parent's children, so parent quality equals assignment quality.
- **Tables** become chunks after multi-page merging and splitting. Captions, sources and unit lines are separate (B-7-05, B-6-16), and `monetary_unit` is often lost.
- **Figures** become an `image_caption` child whose content is a file path until Phase 10b (B-6-14, B-6-18).
- **Silent drops between layout and chunks.** Traced with `trace_harness.py`, block by block:
  1. `Table` blocks on pages under 50 characters (P2-18 skip). Correct.
  2. Extraction returning `None` (empty clip text, or all tiers failing with no image). 0 of 913 in 2025_08.
  3. The garbage filter (B-6-04, B-6-16). This is the main loss: 46 blocks in 2025_08 and 69 in OD, including 1 whole table and every figure caption.
  4. Multi-page merging drops only true fragments. Verified by reading `_merge_multi_page_tables` (`:279-321`).
  5. Text inside pictures, which is never extracted (B-6-18).
  6. Docling's second and later provenances (B-5-03).

  None of these are logged per item. Proposal: log a per-report "dropped by reason" table at INFO, and keep dropped items in a `dropped_blocks` list in the output JSON for audit.
- **Multi-page table merging** (`multi_page_table_handler.py`) now only merges contiguous neighbours with nothing between them (good). The gap check (B-6-02) and the section-range plumbing (B-6-01) are noise or dead.

### Wired-and-working inventory (Phase 7)
| Component / flag | Status | Evidence |
|---|---|---|
| `_create_parent_chunks_from_toc` | Runs; page ranges wrong for unsorted TOCs | B-7-02 |
| `start_y_position` / `heading_positions` | Runs; values often from another page | B-7-01 |
| `_find_best_parent_for_page` | Runs; reproduced 100%; misassigns 10–57% of numbered headers | `sim_assign.py` |
| Multi-page table merge (contiguity-gated) | Works | Reading, plus Step 1 |
| `_detect_missing_pages` | Runs; true positives only when a fragment was filtered out upstream | B-6-04 |
| M2-DLQ `_detect_table_sequence_gaps` | Runs; almost all noise | B-6-02 |
| M1 `section_page_ranges` | **Never matches (dead)** | B-6-01 |
| `_split_oversized_content` | Works; repeats misclassified header rows | B-7-04, B-6-09 |
| `chunking.max_parent_chunk_pages` | **Never read** | grep |
| `chunking.multi_page_table_column_similarity_threshold` | Used | `multi_page_table_handler.py:96` |
| `ParentChunk.audit_category` | Always the default "compliance" | B-7-03 |

## Phase 7.5: Hierarchy enrichment (`hierarchy_enricher.py`)

### Data flow
1. `main.py:1055` runs `should_enrich_hierarchy(parents, children)` (`hierarchy_enricher.py:827`). It fires if any one of these holds:
   - fewer than 10 parents;
   - under 30% of children have `len(hierarchy) > 1` ("flat");
   - over 40% of children sit under one parent;
   - one parent has over 80 children.
2. If it fires, `enrich_hierarchy(..., aggressive=reason in (flat, high_concentration, oversized_parent))` runs. For **each parent**:
   - it takes every child **whose page is inside the parent's page range** (`:334`);
   - it regex-detects "sections" in header text and in the first lines of paragraphs (`:502-654`);
   - it creates a sub-parent per detected section (`:656-712`);
   - it assigns the range's children to the nearest preceding section (`:714-770`).
3. `child_updates.update(...)` (`:380`) keeps the **last** parent's assignment for each child.
4. The post-sync step (`:420-432`) overwrites each child's hierarchy with its parent's.
5. `parallel_runner.py:229-238` runs the same thing with `aggressive=False` hard-coded.

### Does it run? (evidence)
It fired only for BR, in all 4 audited runs: local log line 367, `Reason: flat_hierarchy`. It reported `Added 581 sub-sections, updated 1681 child assignments`, then `fixed 1634 child↔parent mismatches`, and `Hierarchy Enrichment: 1 enriched, 3 skipped`.

### Issues

#### B-7.5-01 · critical · Phase 7.5 re-detects the same sections under every overlapping parent, with identical IDs, and lets the widest parent win
- **Location:** `hierarchy_enricher.py`:
  - `:326-380` (loop over all parents, with children chosen **by page range**);
  - `:519` (`seen_sections` is per parent);
  - `:664-671` (the ID hash has no enclosing parent);
  - `:380` (last writer wins);
  - `:674-693` (inherits the enclosing parent's hierarchy);
  - `:700` (single-page range).
- **Root cause, step by step (all reproduced):**
  1. Children are taken by **page range**, not by `parent_chunk_id` (`:334`, `_get_children_in_range`). BR's pre-7.5 parents overlap, above all the garbage L1 "Corporation" [5,214]. So a section heading on p.22 is detected under "Formation of various Committees 1.4" [21,26], "I AN OVERVIEW…" [21,22], "Organisational setup of PRIs 1.2" [22,22], "Functioning of PRIs 1.3" [22,22] and "Corporation": 5 times.
  2. The sub-parent `chunk_id` is `md5(report_id:section_id:title:page)` (`:664-671`). It doesn't depend on the enclosing parent, so the 5 copies have **the same ID**, and every copy is appended to `new_parents` (`:372-374`). Result: 639 parents with 329 unique IDs, and "1.1.1 State Profile" ×5.
  3. `child_updates.update(section_assignments)` (`:380`) runs once per parent in list order. "Corporation" is parent #51 of 58 and spans p.5–214, so its assignment overwrites almost everything: 1,681 children are finally assigned to sub-sections detected under "Corporation".
  4. Those sub-parents inherit `level_1` from the enclosing parent's hierarchy (`:681-693`). With "Corporation" enclosing, `level_1 = "Corporation"`, and the post-sync (`:420-432`) copies it to 1,645 children.
  5. Sub-parent `page_range_physical = [page, page]` (`:700`). Children after the heading page fall "outside" their parent: 611 children.
  6. Level is absolute by pattern (`numbered` means L2, `roman_dot` means L3), not relative to the enclosing parent. List items such as "ii For the aforesaid period…" (`roman_*`, `:130-133`, in aggressive mode where paragraph first lines are scanned at `:548-557`) become L3 parents. Detected sections duplicating existing TOC parents ("1.2 Organisational set-up of PRIs" vs TOC "Organisational setup of PRIs 1.2") aren't checked against the TOC.
  7. `ParentChunk` has no `parent_chunk_id`, `section_id` or `detected_by` fields (`data_contracts.py:145-192`), so Pydantic drops the link from each sub-parent to its enclosing parent at assembly. The output tree can't be rebuilt.
- **Why it fired only for BR:**
  - `should_enrich_hierarchy` condition 2 (`:865-881`) counts children with `len(hierarchy) > 1`.
  - BR's printed-contents TOC came out with 35 L1 and 23 L2 entries, where every section "1.2", "1.3" and so on became L1 (Agent A's P4-01).
  - So only 180/1,719 children (10.5%) had a level_2, and the reason was `flat_hierarchy`. The other reports had nested TOCs (≥30% deep).
  - The trigger is effectively "Phase 4 produced a flat TOC". The first flat-TOC report hits this bug.
- **Explains Step 1:** P7-01 fully, including the 525 BR Phase 10a summaries downstream (P10a-03).
- **Evidence:** `step2/B/repro_p7_01.py` output:

  ```
  pre-7.5 levels of the 58 parents: {1: 35, 2: 23}
  children with len(hierarchy)>1: 180 / 1719
  should_enrich: (True, 'flat_hierarchy')
  Corporation parent: [5, 214] children assigned in Phase 7: 37
  after 7.5: parents 639 unique ids 329 dup ids 268 max dup 5
  children with level_1=Corporation: 1645
  children outside their parent page range: 611
  enclosing parent whose sub-sections won the children: [('Corporation', 1681)]
  ```

- **Fix proposal:**
  1. **Scope by membership.** Each parent scans only children with `parent_chunk_id == parent.chunk_id`, so each child is examined exactly once. This alone removes the duplication and the "Corporation" takeover.
  2. **Deduplicate globally.** Keep a report-wide `seen` keyed by the normalised section number (or normalised title) and page. Skip any detected section that matches an **existing** parent (same section number anywhere in its title, or title similarity ≥0.85).
  3. **Accept only numbered sections consistent with the enclosing parent.** Under "5.5 …", accept "5.5.x" and deeper; for a chapter parent "V …", accept "5.x". Drop the roman, lettered and bullet patterns as parent creators; they are list items in CAG reports. Set the level to enclosing level + number depth.
  4. **Compute page ranges forward:** from the heading page to the page before the next detected sibling or higher heading, capped at the enclosing parent's end.
  5. **Add a safety valve.** If the output has duplicate IDs, more than 3× the original parent count, or any child outside its parent's range, log an ERROR and **return the input unchanged**.
  6. Carry `parent_chunk_id` (the enclosing parent) through `ParentChunk`: add optional `parent_chunk_id` and `detected_by` fields to the contract.
  7. Make `parallel_runner.py:236` pass the same `aggressive` flag as `main.py:1101`. The two modes behave differently today.
  8. The real fix is upstream: once the printed-TOC levels are right (Agent A's P4-01), BR won't be flat. Also consider replacing the `flat_hierarchy` trigger with "TOC has no L2 entries **and** some parent has more than 80 children".
- **Risk / effort:**
  - (1), (2), (5) and (7) are S and remove the catastrophic behaviour.
  - (3), (4) and (6) are M.
  - Regression: rerun `repro_p7_01.py` and assert that the IDs are unique and no child falls outside its parent's range.
- **Confidence:** verified by running (exact reproduction).

#### B-7.5-02 · medium · The post-sync step overwrites every child's hierarchy even when enrichment did not touch it
- **Location:** `hierarchy_enricher.py:417-434`.
- **Root cause:**
  - It copies the parent hierarchy onto any child whose hierarchy differs.
  - When parent IDs are duplicated, the lookup `{p.chunk_id: p}` keeps the **last** duplicate. That is typically the copy detected under the widest parent (e.g. "Corporation"), whatever the child's actual section.
- **Explains Step 1:** P7-01 (the 1,634 "fixed" mismatches are mostly children being given `level_1 = "Corporation"`).
- **Fix proposal:** unnecessary once IDs are unique (B-7.5-01 items 1–2). Keep it, but after the dedup.
- **Risk / effort:** S. **Confidence:** verified by running.

#### B-7.5-03 · low · The trigger thresholds and the sequential and parallel runners diverge
- **Location:**
  - `hierarchy_enricher.py:860-907`: the thresholds are hard-coded (10 parents, 30% deep, 40% concentration, 80 children), not in `parsing_config.yaml`;
  - `parallel_runner.py:236`: `aggressive=False`, vs `main.py:1101`, which is aggressive for 3 of the 4 reasons.
- **Evidence:** production runs sequential mode (no `PARALLEL MODE` in any run log), so the parallel path is untested in production.
- **Fix proposal:** move the thresholds to config and share one `run_phase_7_5(task)` helper between both runners.
- **Risk / effort:** S. **Confidence:** verified by reading and the logs.

### Wired-and-working inventory (Phase 7.5)
| Component / flag | Status | Evidence |
|---|---|---|
| `should_enrich_hierarchy` | Runs; fires only on flat TOCs (1 of 26 reports) | Log line 367 |
| `enrich_hierarchy` | **Runs and is broken** (duplicate IDs, a takeover by the widest parent) | B-7.5-01 |
| Post-sync of child hierarchy | Runs; spreads the damage | B-7.5-02 |
| Sub-parent link (`parent_chunk_id`, `detected_by`) | **Dropped by the `ParentChunk` schema** | B-7.5-01 item 7 |
| Parallel-mode Phase 7.5 | Different flags; unused in production | B-7.5-03 |

## Phase 5: Layout analysis (Docling)

### Data flow
1. `LayoutAnalysisService.analyze_layout` (`layout_analysis_service.py:116`) runs `DocumentConverter.convert` on the whole PDF:
   - `do_ocr=False`, TableFormer ACCURATE, cell matching on;
   - timeout = max(conversion_timeout, pages × per-page).
2. `_convert_docling_doc_to_standard_format` (`:241`) handles each `doc.iterate_items()` item (body layer only):
   - It uses the first provenance; the bbox is flipped to a top-left origin (correct: y values match PyMuPDF exactly in the output).
   - Confidence comes from `getattr(item, "score", 1.0)`.
   - The label comes from `type(item).__name__.replace("Item", "")` and is mapped by `_map_docling_label`.
   - For tables, `item.export_to_markdown(doc)` is stored as `docling_table_markdown` if it has at least `table_min_non_empty_cells` non-empty cells.
3. `_validate_and_sort_results` (`:371`) sorts the blocks on each page by (y0, x0). The result goes to `task.layout[page] = [block…]`.

### Does it run? (evidence)
Yes. Every report logs `Docling conversion complete`. Across all 26 outputs, child `layout_label` takes only 4 values: `Text` 16,123, `Section-header` 4,087, `Table` 1,139, `Picture` 656. `layout_confidence` is 1.0 on **all 22,005** children.

### Issues

#### B-5-01 · high · Docling's labels are thrown away: footnotes, captions and list items all become "Text"
- **Location:** `layout_analysis_service.py:286-287` and `:329-346`.
- **Root cause:**
  - In Docling v2 the element type lives in `item.label` (a `DocItemLabel`), not in the Python class.
  - Footnotes and captions are `TextItem` with `label == footnote` or `caption`, so the class name is "Text".
  - List items are `ListItem`, and `"ListItem".replace("Item", "")` is `"List"`, which is not in the mapping, so they default to "Text".
  - So the mapping keys `ListItem`, `Footnote`, `Caption`, `PageHeader`, `PageFooter` and `Figure` can never match. The router entries for `Footnote` (`content_extraction_service.py:119`, `_extract_footnote`) and `List-item` are dead code. The `footnote` and `list` content types never occur (0 in 26 outputs).
  - Docling also binds captions and footnotes to their table or picture (`TableItem.captions`, `.footnotes`, `caption_text(doc)`). The pipeline never reads them.
- **Explains Step 1:**
  - P6-12: footnotes are never linked, become standalone chunks and are extracted as findings;
  - P6-04: table captions are "Table on page N" or a random paragraph, although Docling had the right caption;
  - P7-04: captions and sources are tiny separate chunks;
  - part of P9-13: footnotes extracted as findings.
- **Evidence:** `step2/B/docling_labels.py`, which runs Docling with the pipeline's exact options on GPU 2025_08 pp.19–22 (5.6 s):

  ```
  12 ('Text', 'text')   8 ('SectionHeader', 'section_header')   5 ('List', 'list_item')
   4 ('Text', 'caption') 3 ('Text', 'footnote')  3 ('Table', 'table')  1 ('Picture', 'picture')
   Text caption 'Table 1: Details of core grant (Operation and Maintenance) for the per'
   Text footnote '1 The Government of India has unveiled its vision for the next decade,'
  ```

  Every caption, footnote and list item on those pages reaches the pipeline as "Text".
- **Fix proposal:**
  - Map from `item.label.value`: `footnote` becomes Footnote, `caption` becomes Caption (a new "caption" handling), `list_item` becomes List-item, `section_header` and `title` become header, `picture` and `chart` become Picture, and `table` becomes Table.
  - For `TableItem` and `PictureItem`, store `caption_text(doc)` and the resolved footnote texts on the block (`docling_caption`, `docling_footnotes`), and use them in Phase 6 as `structured_data.title` and `footnotes`.
  - Skip caption `TextItem`s already bound to a table or picture, to avoid duplicating them as paragraphs.
  - Then `_extract_footnote` starts working and `footnote_index` in Phase 8 (Agent C) gets populated.
- **Risk / effort:**
  - M. Content types `footnote` and `list` will start appearing, so downstream consumers must accept them. `ChildChunk` already allows both (`data_contracts.py:200-208`).
  - Phase 9 extractors should skip `footnote` chunks for findings (hand-off to the main session).
- **Confidence:** verified by running.

#### B-5-02 · medium · The layout confidence threshold is a no-op: Docling v2 items have no `score`
- **Location:** `layout_analysis_service.py:278-283`; config `layout.confidence_threshold: 0.65`.
- **Root cause:** `getattr(item, "score", 1.0)` always returns 1.0. `docling_labels.py` shows `NO-SCORE-ATTR` for every item. Low-confidence layout clusters, such as banners labelled Table and photos labelled Picture, are never filtered, and `layout_confidence` in every chunk is a constant 1.0.
- **Explains Step 1:** P6-10 (chapter banners detected as tables reach Tier 3), and part of P6-07.
- **Fix proposal:** either remove the threshold and the field (honest), or read the cluster confidence from `conversion_result.pages[i].predictions.layout.clusters` (each cluster has `.confidence`) and join it to items through `prov` bbox overlap. The second option is worth it only if we want to filter; banner and photo filtering is better done by explicit rules (B-6-0x).
- **Risk / effort:** S (remove) or M (real scores). **Confidence:** verified by running.

#### B-5-03 · low · Only the first provenance of each item is kept
- **Location:** `layout_analysis_service.py:253`.
- **Root cause:** items with several provenances (a paragraph continuing into a second column or onto the next page) keep only `prov[0]`'s page and bbox. Text is then re-read by PyMuPDF from that bbox only, so the continuation text is lost unless Docling also emitted it as a separate item.
- **Evidence:** `step2/B/multi_prov.py` on OD pp.20–50: 281 items, **0** with more than one provenance. Docling 2.74 splits cross-column and cross-page text into separate items, so this is **latent only**.
- **Fix proposal:** emit one block per provenance entry (defensive).
- **Risk / effort:** S. **Confidence:** verified by running (not triggered).

### Wired-and-working inventory (Phase 5)
| Component / flag | Status | Evidence |
|---|---|---|
| Docling conversion with the page-scaled timeout | Works | Every run log |
| Bbox conversion to top-left origin | Works | `start_y` equals the child `bbox[1]` where the match is correct (B-7-01) |
| `layout.confidence_threshold` | **No-op** (no `score` attribute) | B-5-02 |
| Label mapping: Footnote, Caption, List-item, Page-header, Figure | **Never matches (dead)** | B-5-01 |
| `layout.table_min_non_empty_cells` gate on Docling markdown | Works | Reading |
| `layout.tableformer_mode: ACCURATE` | Works | Config and log |
| Docling's caption and footnote binding (`TableItem.captions` / `.footnotes`) | **Not used** | B-5-01 |
| Text inside pictures | **Skipped** | B-6-18 |

## Phase 6: Content extraction and tables

### Data flow
1. `ContentExtractionService.extract_content` (`content_extraction_service.py:943`) routes every layout block through `_route_block` (`:350`), page by page.
2. **Table blocks** (`:377-582`):
   - A Table block on a page with under 50 characters of text is skipped (P2-18).
   - pdfmux runs if enabled; it never is (B-6-13).
   - **Native PDFs:** Tier 1 is `PdfplumberTableExtractor.extract`: crop to the Docling bbox, then the `lines` strategy and the `text` fallback, the better one chosen by token coverage; then clean, repair font shift and reversal, compute confidence, make markdown and a `StructuredTable`.
   - If that returns `None`: Tier 2 is Docling's `docling_table_markdown` re-parsed by `StructuredTableExtractor`; otherwise Tier 3 saves a PNG crop for Gemini (`_extract_and_save_visual`).
   - **Scanned PDFs:** Tier 2, then Tier 3.
3. **Picture blocks:** a PNG crop is saved and the chunk content is the file path (`:767-819`).
4. **Text, Section-header and List-item blocks:** `TextExtractor.extract` clips PyMuPDF text to the bbox (`sort=True`), then:
   - normalises ligatures, hyphens and whitespace;
   - `repair_font_shift`;
   - `ocr_normalizer.normalize_headers`;
   - reversal repair when `is_reversed`;
   - letter-spacing repair;
   - classifies the type.
5. `_merge_cross_page_paragraphs` (`:848`).
6. `ChunkFilterService.filter_extracted_content`: merge short runs, then minimum length, garbage patterns, duplicates, whitespace ratio.
7. The result is `task.extracted_content`.

### Tier cascade review
- **Tier 1 selection:**
  - Tier 1 (pdfplumber) always runs first on native PDFs. It returns `None` for rotated pages (`page.rotation != 0`, deferring to Docling), for no table found, or for confidence under `table_min_confidence` (0.2).
  - Its confidence has 3 penalties (empty ratio, column consistency, numeric ratio). Column consistency is always 1.0, because pdfplumber rows are equal-length after extraction, so that penalty is dead.
  - With a 0.2 floor, only tables hit by all three penalties (score 0.1) are rejected. In practice, anything pdfplumber finds is accepted, including the `text_fallback` output that splits words across columns (509 chunks, `pdfplumber-text_fallback`).
- **Tier 2** (Docling) is used 89 times across the 26 outputs, and on the vertical-text pages where it was the fallback. Its markdown is padded (B-6-04) and re-parsed through a lossy markdown step (B-6-10). Docling's structured cells (`item.data.table_cells`, with row and column spans and header flags) are ignored.
  - **Improvement:** build `StructuredTable` directly from `table_cells`. The header rows are then Docling's `column_header` flags, which fixes B-6-09 for Tier 2.
- **Tier 3** saves an image for Gemini (598 `gemini-2.5-flash-vision` chunks in the outputs). Step 1 found that on post-fix reports every Tier 3 page is a chapter banner that Docling labelled a table. With the confidence threshold dead (B-5-02) nothing stops these. A cheap guard: if the region's PyMuPDF text is under 40 characters with no digits, or is one line in a large font, treat it as a header, not a table.
- **Recommended order:** pdfplumber `lines` only when the ruling covers 90% or more of the region's tokens; otherwise Docling cells; `text_fallback` only when Docling has no table. Today `text_fallback` beats Docling because Docling runs only when pdfplumber returns `None`.

### Wired-and-working inventory (Phase 6)
| Component / flag | Status | Evidence |
|---|---|---|
| Tier 1 pdfplumber (`lines`) | Works | 535 chunks |
| Tier 1 `text_fallback` | Runs; splits cells (P6-00 pre-fix; the post-fix stitcher helps) | 509 chunks |
| Tier 2 Docling | Runs; padded markdown dropped by the filter; lossy re-parse | B-6-04, B-6-10 |
| Tier 3 Gemini crop | Runs; mostly banners post-fix | Step 1, P6-10 |
| pdfmux (`content_extraction.pdfmux.enabled`) | **Disabled (dead code)** | B-6-13 |
| `_extract_footnote` | **Never called** (no Footnote label) | B-5-01 |
| `_classify_visual_subtype` | Runs with an empty caption; always "photo" or null | B-6-15 |
| Rotation handling (`page.rotation`) | Works for `/Rotate` pages | GPU 2025_08 |
| Vertical text on `/Rotate 0` pages | **Not handled** | B-6-05 |
| Font-shift repair (29) | Works | P6-00 fixed in GPU |
| Letter-spacing repair | Works | Step 1 |
| Rupee font mapping | **Missing** | B-6-06 |
| Cross-page paragraph merge | Works (16 merges in 2025_08) | Log |
| Garbage filter | Runs; over-filters captions, headings, units and Docling tables | B-6-04, B-6-16 |
| P1-11 rotated-page red flag | Runs (trace only) | Reading |
| DLQ image save (`_save_failed_extraction`) | Runs only on extractor exceptions; writes to local `data/dead_letter_queue`, which is not uploaded | Reading |

#### B-6-04 · medium · The garbage filter drops whole Docling tables as "excessive whitespace", because Docling pads its markdown columns
- **Location:**
  - `chunk_filter_service.py:169-174`: whitespace ratio > 0.7 is rejected, for **every** content type, including `table_markdown`;
  - `layout_analysis_service.py:299`: `item.export_to_markdown(doc)` pads every cell to its column's widest cell.
- **Root cause:**
  - Docling's markdown aligns columns with spaces. One long cell in a column (such as a paragraph of audit observations) pads every other row of that column with hundreds of spaces.
  - The filter treats the item as whitespace garbage and silently drops the **entire table**. No DLQ entry, no Tier 3, no WARNING: it only adds to the "Filtered N garbage chunks" count.
  - On native PDFs this hits exactly the tables pdfplumber couldn't read (Tier 2 is used only when Tier 1 fails), which are the wide text-heavy annexure tables.
- **Explains Step 1:**
  - P6-02, for the post-fix GPU 2025_08 p.145 case. The "missing page" in `table_141_67_70_merged` is not a merge bug: the p.145 fragment was dropped before chunking, then the handler merged pp.144 and 146 across the gap and logged `Missing pages detected: {145}`.
  - Extent (`trace_harness.py` on 8 reports with the current code): 1 table dropped in GPU 2025_08 (p.145) and 1 in 2023_19 (p.204, `Scheduled completion date …`); 0 in OD, JH, BR, HP_2019, HP_2022 and KA. It is rare, but each case silently loses a whole annexure page, and it is exactly the wide, text-heavy tables that nothing else captures.
- **Evidence:**
  - `step2/B/p145.py` runs Docling with the pipeline's options on p.145 (0-based), then the pipeline's own `ChunkFilterService._validate_content`: `table rows 8 cols 2 chars 10938 whitespace ratio 0.728` gives `filter verdict: (False, 'excessive_whitespace')`.
  - The GPU log for p.145 shows `pdfplumber: No table found on page 145` and then `Native PDF: pdfplumber failed, using Docling (page 145) - Tier 2`, so Tier 2 produced the table, and the output has **no chunk at all** on p.145.
  - Docling tables that survived in the GPU output have whitespace ratios up to 0.66 (15 tables), right below the cutoff.
- **Fix proposal:**
  - Normalise markdown before storing it: collapse runs of spaces inside cells (`re.sub(r" {2,}", " ", line)` per row, or rebuild the markdown from `item.data.table_cells`).
  - Exempt `table_markdown` from the whitespace check. Measure on non-space, non-pipe, non-dash characters if a check is still wanted.
  - Any table dropped by the filter should be logged at WARNING with page and reason.
- **Risk / effort:** S. **Confidence:** verified by running.

#### B-6-16 · medium–high · The garbage filter drops chapter titles, figure and annexure captions, unit lines, and repeated section headers
- **Location:**
  - `chunk_filter_service.py:37-45`: `MIN_LENGTH["paragraph"] = 30`;
  - `:150-153`;
  - `:161-167`: duplicates dropped after the 2nd occurrence, **headers included**;
  - `:90-130`: `_merge_short_runs` only joins **consecutive** short paragraphs.
- **Root cause:**
  - Any "Text" block under 30 characters is dropped. Because Docling's caption and label information is discarded (B-5-01), captions and chapter titles arrive as short "Text": "Figure 5: Argo Float Density", "Annexure I (Refer Para 4.1)", "Chapter - IV Data Management", "(₹ in crore)", "Executive Summary".
  - Section headers such as "Recommendations" appear in every chapter, and every one after the 2nd is dropped as a duplicate. The section loses its heading chunk, which is also the anchor that parent assignment and Phase 9 recommendation detection rely on.
- **Explains Step 1:**
  - P6-04: figure and annexure captions don't exist in the output at all;
  - P7-02: lost heading anchors;
  - part of P9-01: recommendation sections lose their "Recommendations" heading;
  - `monetary_unit` is lost for tables whose "(₹ in crore)" line sat outside the table (B-6-11).
- **Evidence:**
  - `step2/B/trace_harness.py` runs the real Phase 5 and Phase 6 services on GPU 2025_08 and records each block's filter verdict (`trace_2025_08.json`). 46 blocks were dropped:
    - 11 figure or annexure captions (e.g. p.42 `Figure 5: Argo Float Density`, p.132 `Annexure I (Refer Para 4.1)`);
    - 6 chapter titles (`Chapter - II`, `Chapter - IV Data Management`);
    - 2 `(₹ in crore)` unit lines;
    - `Executive Summary` (p.8);
    - 4 × `Recommendations` headers (pp.13–15, as duplicates);
    - 12 × the running header `Report No. 8 of 2025` (correctly dropped);
    - 1 table: p.145, `excessive_whitespace`, the B-6-04 case.
  - **OD:** 69 blocks dropped. 38 source or note lines (`(Source: UDISE+ database)`), 5 captions (`Appendix 5.1`, `Picture 6.1; dated 14-08-2023`), 3 unit lines, and 23 other short texts.
  - **JH:** 98 blocks dropped, **55 of them `(₹ in crore)` unit lines on 47 pages**, plus 10 source lines and 3 captions. Correspondingly, 61 of 128 JH tables have `monetary_unit = null` (OD 46/85, GPU 23/40). The unit sat on a line above the table and was deleted before anything could bind it.
  - Per-report counts for BR, HP_2022, KA, HP_2019 and 2023_19 are in the appendix at the end (`summarize_traces.py`).
- **Fix proposal:**
  - Never length-filter a block that matches caption, heading or unit patterns: `^(Table|Chart|Figure|Fig\.|Annexure|Appendix|Exhibit|Box|Map)\s*[\dIVXA-Z]`, `^Chapter\b`, `^\(?(₹|Rs\.?)\s*in\s+(crore|lakh)`, `^\((Source|Note)`. Attach them to the neighbouring table or figure (B-7-05) or keep them as headers.
  - Deduplicate by **position**, not only by text: a string repeated on many pages at the same y (±5 pt) in the top or bottom band is a running header or footer. Section headers with body text below them are never duplicates.
- **Risk / effort:** S. **Confidence:** verified by running.

#### B-6-05 · high · Text drawn vertically on portrait pages (page rotation 0) is extracted in reversed word order, and its tables with reversed characters
- **Location:**
  - `text_extractor.py:146-167`: rotation handling only when `page.rotation != 0`;
  - `:211`: `get_text("text", clip, sort=True)`;
  - `text_repair.is_reversed`: character reversal only;
  - `pdfplumber_table_extractor`: no orientation handling (next section).
- **Root cause:**
  - Many CAG annexures are landscape tables typeset **rotated inside a portrait page**. The page has `/Rotate 0`, but every text line has direction `(0,-1)` and reads bottom-to-top.
  - PyMuPDF's `sort=True` orders words top-to-bottom, so word order comes out reversed ("2022 March ended year the for Government) (Local Report Audit").
  - pdfplumber reads characters in x/y order, so strings come out character-reversed ("skrameR").
  - `is_reversed` fixes only character-reversed text, and only when stop-word hits allow it. The P1-11 derotation handles only `page.rotation`.
- **Explains Step 1:** P6-01 (BR pp.169–219, KA pp.79, 80, 90). Also part of P6-00 for union reports that were never re-run after the fixes.
- **Evidence:** `step2/B/rotated_text.py` scans all 26 PDFs for pages with `rotation == 0` whose text is more than 50% vertical:

  | Report | Vertical pages | Examples |
  |---|---|---|
  | 2023_07 | 16 | pp.88–93… |
  | 2023_19 | **54** | pp.203–208… |
  | 2025_26 | 26 | pp.128–133… |
  | BR | 30 | pp.169–175… |
  | KA | 3 | 79, 80, 90 |

  `step2/B/rotated_fix_demo.py` shows current vs fixed extraction:

  ```
  BR p175 current : budget budget budget budget budgetAppendices percentage) in in in ... 2017-182017-182017-18
  BR p175 fixed   : Appendices | Appendix-5.2 | (Refer: Paragraph-5.2.1, Page - 46) | A. Service level benchmarks for SWM (March 2017/ March 2018) ...
  KA p79 current  : 20.20 37.69 41.74 99.63 5.84 ... Excess release lakh) demand/Appendices in (₹ of UDD ...
  KA p79 fixed    : Appendices | Appendix 2.9 | (Reference: Paragraph 2.9.6/Page 17) | Month-wise details of amount demanded in excess by KWSPFT ...
  ```

  (`page.set_rotation()` does **not** help: PyMuPDF's text coordinates stay unrotated. Tried, same output.)
- **Fix proposal:**
  - **Text:** in `TextExtractor._extract_text_from_bbox`, read `page.get_text("dict", clip=clip)` and, if more than 50% of the characters are in lines with `dir ≈ (0,-1)`, build the text from `get_text("words", clip)` sorted by `(round(x0/4), -y1)`. For `dir ≈ (0,1)`, sort by `(-round(x0/4), y0)`. This is the demo function, about 15 lines.
  - **Tables:** before pdfplumber, detect vertical pages once per page and render a derotated copy (`new_page.show_pdf_page(rect, src, pno, rotate=90)` into a temporary one-page PDF, which transforms the content stream). Then run pdfplumber on that copy with the bbox transformed.
  - Add a word-order check to `preflight_check.py` (Step 1's X-01).
- **Risk / effort:** M. Text is S; the table derotation is M.
- **Confidence:** verified by running (the text demo; the table path is proposed, not run).

#### B-6-06 · low–medium · The rupee sign comes out as a backtick: the "Rupee Foradian" font maps the backtick glyph to ₹
- **Location:** `text_extractor.py:47-108` (`_normalize_text` has no rupee mapping); the same applies to pdfplumber cell text.
- **Root cause:**
  - Older CAG reports set ₹ with the "Rupee Foradian" or "RupeeForadian" font, whose backtick code point (0x60) draws ₹.
  - The text layer says `` ` ``, and nothing maps it back.
- **Explains Step 1:** P6-11.
- **Evidence:** `step2/B` font scan of the PDFs; every backtick span is in a Rupee font:

  | Report | Backtick spans | Font |
  |---|---|---|
  | HP_2019 | 209 | Rupee Foradian |
  | 2020_16 | 389 | RupeeForadian |
  | 2023_19 | 390 | |
  | 2024_13 | 798 | |

  OD has 2 Calibri backticks, which are genuine.
- **Fix proposal:** font-aware replacement in both extractors: when a span's or char's font name matches `/rupee/i`, replace `` ` `` with `₹`. A cheap fallback is `re.sub(r"`(?=\s?[\d(])", "₹", text)` in `_normalize_text` and in the table cell cleaner.
- **Risk / effort:** S. **Confidence:** verified by running (font scan).

#### B-6-07 · low · The hyphen rejoin merges year ranges split across lines ("2018-\n19" becomes "201819")
- **Location:** `text_extractor.py:100`: `re.sub(r"-\s*\n\s*", "", text)`.
- **Root cause:** every hyphen at a line end is treated as a soft hyphenation, including numeric ranges and compound words.
- **Evidence:** 41 occurrences across 9 reports where the PDF has `YYYY-\nYY` and the chunk has `YYYYYY`:

  | Report | Occurrences |
  |---|---|
  | 2025_06 | 16 |
  | OD | 11 |
  | HP_2019 | 4 |
  | 2025_26 | 3 |
  | others | 1–2 each |

  For example, 2020_16 p.106 "2014-15 to 201819"; 2025_06 p.42 "during the year 202122". These break temporal extraction and number search.
- **Fix proposal:** keep the hyphen when both sides are digits: `re.sub(r"(?<=\d)-\s*\n\s*(?=\d)", "-", text)` before the generic rule. Keep the hyphen when the next line starts with a capital letter.
- **Risk / effort:** S. **Confidence:** verified by running.

#### B-6-08 · low · The curly-quote normalisation is broken by a stray triple-quoted string
- **Location:** `text_extractor.py:87-90`.
- **Root cause:**
  - The source file's curly quotes were flattened to straight quotes. Lines 89–90 now read `""": "'", … """: "'"`, which Python parses as one triple-quoted string key.
  - Left and right curly quotes (`“ ” ‘ ’`) are never normalised, so BM25 and regexes that expect `'` miss "Government’s".
- **Fix proposal:** use escaped code points (`"“"`, `"”"`, `"‘"`, `"’"`).
- **Risk / effort:** S. **Confidence:** verified by reading.

#### B-6-09 · medium–high · The header-row heuristic turns the first data rows of text-heavy tables into headers
- **Location:** `structured_table_extractor.py:237-274` (`_detect_header_rows`); `_is_numeric` at `:710`.
- **Root cause:**
  - Rows 2–3 count as headers when 50% or fewer of their cells are numeric and more than 70% are under 30 characters.
  - A typical CAG data row `1. | Nor | Nirmand | Kullu | 0.39` has 2 numeric cells out of 5 (`float("1.")` succeeds) and all 5 are short, so it becomes a header.
  - The markdown's own `---` separator, which marks where the header ends (pdfplumber's `_to_markdown` always puts it after row 0), is ignored.
  - Header rows are then repeated in every split piece (B-7-04) and excluded from "data" everywhere downstream: entity extraction, totals.
- **Explains Step 1:** P6-03 (the repeated first data row).
- **Evidence:**
  - Across all 26 outputs, 970 of 1,135 tables with rows have **more than one** header row, and **239 (21%)** have a "header" row whose first cell is a serial number (`^\d{1,3}\.?$`), i.e. a data row.
  - In HP_2022 `table_109_71_126_merged`, all 3 parts have `num_header_rows=3`. The headers are `['', '2017-18', '', …]`, `['', 'Sl. No.', '', 'Name of Gram Panchayat', …]` and `['1.', '', 'Nor', '', 'Nirmand', '', 'Kullu', '', '0.39', '']`, so data row 1 is repeated in every part.
  - The interleaved empty columns come from double rules that `_drop_empty_lines` cannot remove because the spanning `2017-18` cell fills them.
- **Severity note:** it affects about 21% of tables, so treat it as medium–high.
- **Fix proposal:** header rows are the rows above the markdown separator. Allow extra header rows only when a row has no numeric cells and at least one empty (spanned) cell, which is the multi-level header pattern.
- **Risk / effort:** S. **Confidence:** verified by reading.

#### B-6-10 · medium · The markdown parser takes a leading caption line as row 0 and doesn't skip a separator that isn't on line 2
- **Location:**
  - `structured_table_extractor.py:202-235`: `num_cols = len(raw_data[0])` (`:161`); the separator is skipped only at `i == 1` (`:220`);
  - `_extract_title` (`:736-751`): "the first non-pipe line".
- **Root cause:**
  - Docling's `export_to_markdown` puts the item's caption text (or whatever Docling bound as caption, often a running header) on a line **before** the table.
  - The parser makes that a 1-cell row 0, so `num_cols` becomes 1. The real separator on line 3 becomes a data row of `---`, and every other cell has no column metadata.
  - `_extract_title` returns that line, which is how 4 GPU tables got the title "Report No. 8 of 2025".
- **Explains Step 1:** P6-04 (the "Report No. 8 of 2025" titles), and wrong column metadata for Docling tables.
- **Evidence:** `step2/B/p145.py`: Docling's markdown starts `Report No. 8 of 2025\n\n| Audit observations | …`. `StructuredTableExtractor.extract` gives `num_cols=1`.
- **Fix proposal:**
  - Split off leading non-pipe lines as `caption_candidates`, and use them as the title only if they match `TABLE_TITLE_RE` or Docling says they are a caption (B-5-01).
  - Detect the separator by pattern on any line, and take `num_cols` as the maximum cell count over table rows.
- **Risk / effort:** S. **Confidence:** verified by running.

#### B-6-11 · medium · Table cells without a unit are normalised as rupees; the table's "(₹ in crore)" unit is detected but never applied
- **Location:**
  - `structured_table_extractor.py:44-53`: `plain_number` counts as CURRENCY;
  - `:662-678`: no unit means ×100;
  - `:753-790`: `monetary_unit` is detected but not used for cells.
- **Root cause:**
  - Every plain number (counts, years such as "2019", serial numbers, percentages without `%`) becomes `data_type=CURRENCY` with `normalized_value = value × 100` paise.
  - In a "(₹ in crore)" table, 847.71 is stored as 84,771 paise (₹847.71) instead of 847.71 × 10⁹. That is out by 10⁷.
- **Explains Step 1:** feeds P9-05 (wrong monetary values) if Phase 9 or the API reads `normalized_value` from tables. Hand-off to the main session's monetary deep dive.
- **Fix proposal:**
  - A plain number is CURRENCY only when the column or table has a monetary unit (caption or header "₹ in crore/lakh", or a column header with ₹/Rs/amount).
  - Then `normalized_value = value × multiplier(monetary_unit)`. Otherwise it is INTEGER or DECIMAL, with no paise value.
- **Risk / effort:** S–M. **Confidence:** verified by reading.

#### B-6-12 · low · Smaller table-extraction defects
All verified by reading.
- **Several tables in one bbox are concatenated into one table.** `pdfplumber_table_extractor.py:216` concatenates rows of **all** tables found in the bbox into one table, even with different column counts. The text fallback takes only `tables_fb[0]` (`:227`).
- **Dead code and a wrong message.** "Attempt 3" (`:237-245`) returns `None` in both branches. The Low-confidence message (`:124`) says "Tier 3" but the caller goes to Docling (Tier 2).
- **The PDF is re-parsed for every table.** `pdfplumber.open(pdf_path)` (`:180`) runs per table, and the page vocabulary (`:225`) is rebuilt per table. On table-heavy reports, cache the document and page once per page.
- **Pipes inside cells aren't escaped.** `_to_markdown` (`:483-520`) doesn't escape `|` inside cells, so the round trip through `StructuredTableExtractor` shifts columns.
- **Totals are missed when column 1 is a serial number.** `_classify_row_type` (`structured_table_extractor.py:449-471`) looks only at the first cell: `| | Total | 42.67 |` and `| 23 | Total | … |` are "data".
- **A new extractor per Docling table.** `content_extraction_service._use_docling_table` (`:732-735`) creates a new `StructuredTableExtractor` per table, ignoring `self.structured_table_extractor`. Cheap, but inconsistent.

#### B-6-13 · low · pdfmux routing is disabled: `pdfmux_router.py` (411 lines) is dead code in production
- **Location:** `parsing_config.yaml:167-168` (`pdfmux.enabled: false`); `content_extraction_service.py:141-181`, `:399-445`.
- **Evidence:** every run logs `pdfmux routing disabled in config` (e.g. state run log line 161).
- **Latent bug if ever enabled:** `PdfmuxRouter.extract_table` (`pdfmux_router.py:157-160`) calls `self._pdfmux.extract_json(pdf_path)` on the **whole PDF for every table block**, then filters to one page. A 100-table report would process the full PDF 100 times.
- **Fix proposal:** remove it, or keep it behind the flag but out of the hot path. The docstrings ("Option D … 0.911 TEDS") describe a path that never runs.
- **Risk / effort:** S. **Confidence:** verified by the run logs and by reading.

#### B-6-18 · medium · Values printed on vector charts are in the PDF's text layer but are thrown away at extraction
- **Location:**
  - `layout_analysis_service.py:246`: `doc.iterate_items()` defaults to `traverse_pictures=False`, so text items **inside** a picture are skipped;
  - `content_extraction_service.py:767-819`: `_extract_and_save_visual` saves a PNG crop and stores the file path as content. It never reads the text under the bbox.
- **Root cause:**
  - Most CAG charts are vector graphics with their data labels and axis labels as real text.
  - Phase 5 skips that text and Phase 6 keeps only an image, so the numbers exist only if Gemini (Phase 10b) re-reads them from pixels. Even then they end up in `structured_data`, not in embeddable `content` (Agent D).
- **Explains Step 1:** P6-05. The chart-page number-recall losses are this: JH p.31 0.38, OD p.22 0.36, GPU p.32 0.39.
- **Evidence:** `step2/B/chart_text.py`, run with Docling on one page:
  - **GPU 2025_08 p.32:** 8 items by default, 49 with `traverse_pictures=True`. The 41 hidden items are the data labels `179.58 159.88 31.48 16.08 …`, and PyMuPDF text inside the picture bbox returns the same values plus the axis label "RUPEES IN CRORES".
  - **OD p.22:** the hidden items include `2018-19 … Budgetary Provision 15737.21 17388.09 17914.92 19885.05 21557.91 Expenditure 14161.88 …`. These are exactly the "Chart 1.1 values missing" in Step 1.
- **Fix proposal:**
  - In `_extract_and_save_visual`, read `page.get_text("text", clip=bbox)` (with the B-6-05 vertical-text handling) and store it as `structured_data.embedded_text`.
  - Put a compact form into `content` together with the caption (B-5-01): `Chart 1.1: … | 2018-19 2019-20 … | Budgetary Provision 15737.21 …`.
  - Use more than about 5 numeric tokens in the embedded text as the "this is a chart" signal for B-6-15. Raster photos have no embedded text.
  - Phase 10b can then be limited to raster charts, or used only to structure the series.
- **Risk / effort:** S. **Confidence:** verified by running.

#### B-6-19 · medium · Footnote reference markers are glued to the preceding word or amount
- **Location:** `text_extractor.py:199-213`: `get_text("text")` drops span flags, so superscripts are indistinguishable from body digits.
- **Root cause:** a superscript "36" after "₹ 1.14 crore" becomes `crore36`, and "vision document¹" becomes `document1`. Amount and word matching (BM25, Phase 9 money and finding regexes) then sees corrupted tokens.
- **Explains Step 1:** P6-12 (`₹ 1.14 crore36 5`, `₹4.57 crore41)`).
- **Evidence:** a span scan counting small digit spans (under 0.8 of the preceding span's size) that directly follow text:
  - BR 199, of which 199 have PyMuPDF's superscript flag (`flags & 1`);
  - GPU 2025_08 110 (95 flagged);
  - OD 64 (63 flagged).

  Example: BR p.21 `'…Gram Sabha' + '2'` at size 7.0 vs 12.0.
- **Fix proposal:**
  - In `TextExtractor`, build the text from `get_text("dict", clip)` spans.
  - Replace a superscript digit span (`flags & 1`, or size under 0.8 of the line median) with a marker such as `[^36]`, and record `(page, marker)`.
  - Phase 8 (Agent C) can then link `[^36]` to the footnote chunk that starts with "36", once footnotes exist (B-5-01).
  - Phase 9 regexes must ignore `[^n]`.
- **Risk / effort:** M. **Confidence:** verified by running.

#### B-6-17 · low · The Phase 6 table and figure counters are always wrong
- **Location:**
  - `main.py:893-904`: tables are counted correctly as `table_markdown`, but figures count `content_type == "figure"`, which never exists (images are `image_caption`);
  - `main.py:920-931`: the corpus totals count `"table"` and `"figure"`, both of which never exist, so the log shows `Tables: 0 Figures: 0`.
- **Explains Step 1:** P6-08.
- **Fix proposal:** count `table_markdown` and `image_caption`, both per report and in the corpus totals. (`main.py` belongs to Agent C; this is the one-line fix.)
- **Risk / effort:** S. **Confidence:** verified by reading, plus the GPU log line `838 blocks (42 tables, 0 figures)` / `Tables: 0`.

#### B-6-14 · low · `ContextualCaptionService` never fires, because image content is a file path
- **Location:**
  - `contextual_caption_service.py:71-87` (`is_generic_caption`) and `:280`;
  - called from `assembly_service.py:234-236` (Agent C's file);
  - the image content is set at `content_extraction_service.py:808-819`.
- **Root cause:**
  - At assembly, image chunks hold `data/extraction_images/charts/…png`. That is longer than 10 characters and contains none of the Florence-2 phrases it looks for, so it is "not generic" and nothing is replaced.
  - The service was written for Florence-2 captions, which were removed in V2.
- **Explains Step 1:** part of P6-06: the path stays as content until Phase 10b replaces it, or forever if 10b skips the image.
- **Fix proposal:**
  - In Phase 6, store the image path in `structured_data.image_path` and give `content` a real caption: Docling's caption (B-5-01) or the nearest `Chart/Figure x.y` line.
  - Phase 10b then appends the extracted description and series (Agent D).
  - Delete the Florence-2 heuristics.
- **Risk / effort:** S in Phase 6. It needs the 10b consumer (Agent D) to read `structured_data.image_path`.
- **Confidence:** verified by reading.

#### B-6-15 · medium · Visual subtype classification runs with an empty caption, so every image is labelled a "photo"
- **Location:** `content_extraction_service.py:674-711`, `:801-806` (`_classify_visual_subtype(caption="", hierarchy={}, …)`).
- **Root cause:**
  - With no caption and no hierarchy, no keyword can match. The result depends only on the layout label: `Picture` becomes "photo", and the `Figure` label never occurs (B-5-01).
  - Across the 26 outputs, 594 image chunks have `visual_subtype` null, and 62 have `structured_data.visual_subtype = "photo"`.
  - So no image is classified as a chart at extraction time, and Phase 10b has to send **every** image to Gemini.
- **Explains Step 1:** P6-07 (photos and banners sent to chart extraction: BR ~86/103, KA, OD), and part of P6-06.
- **Fix proposal:** classify at extraction with cheap signals:
  - Docling's picture classification (`PictureItem.annotations` with `do_picture_classification=True`), which labels bar chart, pie chart, photograph, logo and so on;
  - otherwise vector-vs-raster: a chart region has many vector drawings (`page.get_drawings()` inside the bbox) and text labels; a photo is a single raster image with no text;
  - the nearest caption (`Chart x.y` vs `Photograph`).

  Send only charts, maps and diagrams to Phase 10b. Photos keep their caption only.
- **Risk / effort:** M. Docling picture classification adds model time; the vector heuristic is S.
- **Confidence:** verified by reading plus output counts.

#### B-6-01 · medium · Table `source_chunk_id` is always "temp", so the section-aware checks of multi-page tables are dead code
- **Location:**
  - `content_extraction_service.py:423` and `:742`: `source_chunk_id="temp"`;
  - `multi_page_table_handler.py:198-200`: expected span looked up by `source_chunk_id`;
  - `:319-330`: `same_section` compares "temp" with "temp";
  - `chunking_service.py:155-202`: `_build_section_page_ranges` keys ranges by `"{page}_{title[:30]}"`, never by a chunk ID.
- **Root cause:**
  - The "M1 fix" section-range lookup can never hit: the keys are position keys and the lookup value is "temp".
  - `same_section` is always True, and `section_id` in every DLQ entry is "temp" (the Step 1 observation).
- **Explains Step 1:** P6-09 (`section_id: "temp"`).
- **Fix proposal:** delete the dead section-range plumbing, or do the page-gap check after parent assignment (B-7-01), when real parent IDs exist.
- **Risk / effort:** S. **Confidence:** verified by reading.

#### B-6-02 · low · M2-DLQ flags every page between any two tables up to 5 pages apart
- **Location:** `multi_page_table_handler.py:287-338`.
- **Root cause:**
  - After merging, every page strictly between two consecutive tables (gap 1–5) is logged at WARNING and added to the DLQ as `no_fragment_extracted`.
  - It does not check whether the pages were one table run: there is no column or continuation check, and no check that the gap page contains any table-like text.
  - `same_section` is meaningless (B-6-01).
  - Sequence gaps are found between **separate** tables, which is the normal case: a report has a table on p.30 and another on p.33.
- **Explains Step 1:** P6-09 (post-fix DLQ counts: GPU 31, OD 44, JH 35, BR 40; a sample of 8 held no lost tables).
- **Fix proposal:** only flag a gap page when **both** of these hold:
  - the neighbouring tables would have merged by `_should_merge`'s column and marker rules, ignoring contiguity;
  - the gap page has a pdfplumber-detectable table or at least 3 lines with 3 or more numeric tokens.

  Log at DEBUG. Otherwise drop the M2 entry.
- **Risk / effort:** S. **Confidence:** verified by reading.

#### B-6-03 · low · Normal table fallbacks are logged at ERROR
- **Location:** `content_extraction_service.py:513` (Tier 1 → 2), `:530` (Tier 3), `:550`; `pdfplumber_table_extractor` logs "No table found" at WARNING (GPU log line 177).
- **Root cause:** a fallback is normal routing. On pages where pdfplumber finds no ruled table, Docling is the designed path.
- **Explains Step 1:** P6-10 (139 ERROR lines in the union run).
- **Fix proposal:** INFO for Tier 1→2; WARNING for Tier 3; ERROR only for exceptions.
- **Risk / effort:** S. **Confidence:** verified by reading.

## Step 1 issue coverage

| Step 1 | Explained by | Notes |
|---|---|---|
| P7-01 (Phase 7.5 wrecks BR) | B-7.5-01, B-7.5-02, B-7-02 | Exact reproduction. The trigger is Agent A's flat printed TOC (P4-01) plus the garbage "Corporation" parent from Phase 5.5 |
| P7-02 (wrong parent) | B-7-01, B-7-02, B-6-16 | Main cause: `start_y` copied from another page (Agent A's `toc_reconciliation_service.py:649-668`) plus the deepest-level tiebreak. Pre-fix union also has the TOC page offset |
| P7-03 (heading-only, fragmented parents) | B-7-01 (content goes to the wrong parent), B-7-02 | The rest is Phase 5.5 heading promotion (Agent A, P5.5-01), plus assembly cleanup only removing "artifact" titles (Agent C) |
| P7-04 (tiny chunks) | B-7-05, B-5-01, B-6-16 | No caption binding, no minimum child size |
| P7-05 (stale parent count) | Hand-off | `assembly_service.py:229-230` passes the uncleaned `parent_chunks` to `_build_processing_stats` instead of `cleaned_parents` (Agent C) |
| P6-00 (pre-fix union text defects) | B-6-05 | The fixes in dd10896 cover font shift, letter spacing and `/Rotate` pages. **Vertical text on `/Rotate 0` pages remains**, and affects union 2023_07 (16 pages), 2023_19 (54) and 2025_26 (26) as well as BR and KA. Re-running union won't fix those pages |
| P6-01 (rotated text still reversed) | B-6-05 | `page.rotation`-only handling; a fix was demonstrated |
| P6-02 (page dropped in a multi-page merge) | B-6-04 | GPU p.145: a Docling table dropped as "excessive whitespace" before merging. Pre-fix 2023_19 gap pages 211, 228, 235, 246 and 252 all get a kept table with the **current** code (trace), so those gaps were fixed by dd10896. p.93 has no Docling Table block at all. 2023_19 p.204 is a new whitespace drop |
| P6-03 (split tables repeat the first data row) | B-6-09, B-7-04 | 239 of 1,135 tables have a data row classified as a header |
| P6-04 (generic or wrong captions) | B-5-01, B-6-10, B-6-16, B-7-05 | Docling had the captions; they were discarded, length-filtered, or replaced by the markdown's first line. Registry "Table on page N" and the 10c titles are Agents C and D |
| P6-05 (chart values not embeddable) | B-6-18 | Vector chart labels are skipped at Phase 5 (`traverse_pictures=False`) and never read at Phase 6 |
| P6-06 (photo chunk content is a file path) | B-6-14 | The path is set in Phase 6. `ContextualCaptionService` never fires. 10b skip handling is Agent D |
| P6-07 (photos and banners sent to chart extraction) | B-6-15, B-5-02 | No real classification at extraction |
| P6-08 (figure counter) | B-6-17 | `main.py:899-903`, `:920-931` |
| P6-09 (M2-DLQ noise) | B-6-02, B-6-01 | |
| P6-10 (ERROR-level fallbacks; banners reach Tier 3) | B-6-03, B-5-02 | |
| P6-11 (rupee as backtick) | B-6-06 | The Rupee Foradian font |
| P6-12 (footnotes never linked) | B-5-01, B-6-19 | `footnote_index` population is Agent C, but it has no input until B-5-01 is fixed |
| Low-recall pages (post-fix) | B-6-05 (BR 175/199/216/217/219, KA 79/80), B-6-18 (JH 31/38/88, OD 22/53/68/72/77, GPU 32), B-6-04 (GPU 145), B-6-16 (photo captions and appendix titles: BR 183/190, OD 168) | The remaining residual is running headers, which is correct |
| P8-01 (parents always "compliance") | B-7-03 | Root cause in `chunking_service.py` |
| P10a-03 (525 BR summaries) | B-7.5-01 | Downstream of the duplicate parents |

## Hand-offs

- **Agent A, `toc_reconciliation_service.py:640-668` `_update_heading_positions`:** matches Docling headers to TOC entries by title similarity with no page constraint, and the first match wins. A header's y from another page overwrites the TOC entry's `start_y`. This is the main root cause of P7-02 (B-7-01).
- **Agent A, P4-01:** the printed-TOC parser flattens BR's sections to L1, which is what triggers Phase 7.5. Phase 5.5 also produced the garbage L1 "Corporation" [5,214] in BR, whose range swallows the report.
- **Agent A, the P4 page offset in the pre-fix union** (2025_04, 2025_16): TOC start pages are one page after the real heading. Confirm whether this is fixed in c6e1806.
- **Agent C, P8-01:** the root cause is `chunking_service.py:582-595`, which doesn't pass `audit_category` to `ParentChunk` (B-7-03).
- **Agent C, P7-05:** `assembly_service.py:229-230` computes `processing_stats` from `parent_chunks` rather than `cleaned_parents`.
- **Agent C, P6-08:** `main.py:899-903` and `:920-931` count content types that don't exist (B-6-17).
- **Agent C, `footnote_index`:** it stays empty until Phase 5 keeps Docling's footnote label (B-5-01). After B-6-19, children carry `[^n]` markers that assembly can link.
- **Agent C, `ContextualCaptionService`:** it is called from `assembly_service.py:234-236` and never fires (B-6-14). Delete it, or move caption binding to Phase 6.
- **Agent C / orchestration:** `data/dead_letter_queue` is written by Phase 6 on extractor exceptions but is not in the workflow's upload list (`.github/workflows/run-parsing.yml:237-242`). It is lost with the VM.
- **Agent D, P6-05 / P6-06 / P6-07:**
  - Once Phase 6 stores `structured_data.embedded_text`, `image_path` and a `visual_class` (B-6-14, B-6-15, B-6-18), Phase 10b should process only charts, maps and diagrams, and must not leave a path in `content` when it skips an image.
  - The 10c `_infer_title` (`visual_post_processor.py:203-211`) should prefer the Docling caption.
- **Main session (monetary deep dive):** `StructuredTableExtractor` normalises unit-less table numbers as rupees (×100) and never applies the detected "₹ in crore" unit to cells (B-6-11). Any consumer of `structured_data.rows[].cells[].normalized_value` gets values out by 10⁷.
- **Main session (Phase 9 extractors):**
  - Footnotes will arrive as `content_type="footnote"` after B-5-01; skip them as finding and recommendation sources.
  - The `Recommendations` section headers are currently dropped after the 2nd occurrence (B-6-16), which may matter to `recommendation_extractor` if it keys on headings.
  - Footnote markers are glued to amounts (`crore36`), which affects money regexes (B-6-19).

## Summary (ranked issue list)

| # | ID | Severity | Title | Location |
|---|----|----------|-------|----------|
| 1 | B-7.5-01 | critical | Phase 7.5 re-detects sections under every overlapping parent, with identical IDs, and the widest parent wins | `hierarchy_enricher.py:326-380, 519, 664-700`; trigger at `:865-881` |
| 2 | B-7-01 | high | Parent assignment trusts `start_y` copied from another page; deepest-level tiebreak | `chunking_service.py:580, 821-882`; root in `toc_reconciliation_service.py:649-668` (Agent A) |
| 3 | B-5-01 | high | Docling labels discarded (footnote, caption, list item become "Text"); caption and footnote binding unused | `layout_analysis_service.py:286-287, 329-346` |
| 4 | B-6-16 | medium–high | Garbage filter drops captions, chapter titles, unit lines and repeated section headers | `chunk_filter_service.py:37-45, 150-167` |
| 5 | B-6-05 | high | Vertical text on `/Rotate 0` pages comes out in reversed word order, and its tables with reversed characters | `text_extractor.py:146-213`; `pdfplumber_table_extractor.py:189-194` |
| 6 | B-6-09 | medium–high | First data rows classified as table headers (21% of tables) | `structured_table_extractor.py:237-274` |
| 7 | B-6-04 | medium | Whole Docling tables dropped as "excessive whitespace" (padded markdown) | `chunk_filter_service.py:169-174`; `layout_analysis_service.py:299` |
| 8 | B-6-18 | medium | Vector chart values are in the text layer but are never extracted | `layout_analysis_service.py:246`; `content_extraction_service.py:767-819` |
| 9 | B-6-15 | medium | Visual subtype classified with an empty caption, so every image is a "photo" or null | `content_extraction_service.py:674-711, 801-806` |
| 10 | B-6-19 | medium | Footnote markers glued to words and amounts (`crore36`) | `text_extractor.py:199-213` |
| 11 | B-6-10 | medium | The markdown parser takes the caption line as row 0 (`num_cols=1`) and as the table title | `structured_table_extractor.py:161, 202-235, 736-751` |
| 12 | B-6-11 | medium | Unit-less table numbers normalised as rupees; the "₹ in crore" unit is never applied | `structured_table_extractor.py:44-53, 662-678, 753-790` |
| 13 | B-7-02 | medium | Page ranges assume a page-sorted TOC; `max_parent_chunk_pages` is never read | `chunking_service.py:541-567, 183-200` |
| 14 | B-7-03 | medium | `ParentChunk` built without `audit_category`, `department` or `report_subtype` | `chunking_service.py:582-595, 629-641` |
| 15 | B-5-02 | medium | The layout confidence threshold is a no-op (no `score` attribute) | `layout_analysis_service.py:278-283` |
| 16 | B-7.5-02 | medium | The post-sync spreads the widest duplicate's hierarchy | `hierarchy_enricher.py:417-434` |
| 17 | B-6-01 | medium | Table `source_chunk_id` is always "temp", so the section-aware checks are dead | `content_extraction_service.py:423, 742`; `multi_page_table_handler.py:198-200, 319-330` |
| 18 | B-6-06 | low–medium | Rupee Foradian backtick not mapped to ₹ | `text_extractor.py:47-108` |
| 19 | B-7-04 | low–medium | Split tables repeat header or data rows; 1-row tail pieces | `chunking_service.py:386-419`; `multi_page_table_handler.py:632-639` |
| 20 | B-7-05 | low | No caption, source or unit binding, so tiny chunks | `chunking_service.py:678-745` |
| 21 | B-6-02 | low | M2-DLQ flags every page between tables up to 5 pages apart | `multi_page_table_handler.py:287-338` |
| 22 | B-6-03 | low | Normal table fallbacks logged at ERROR | `content_extraction_service.py:513, 530` |
| 23 | B-6-07 | low | Hyphen rejoin merges "2018-\n19" into "201819" | `text_extractor.py:100` |
| 24 | B-6-08 | low | Curly-quote normalisation broken by a stray triple-quoted string | `text_extractor.py:87-90` |
| 25 | B-6-12 | low | Smaller pdfplumber and table defects (multi-table concatenation, dead Attempt 3, re-open per table, unescaped pipes, totals in column 2) | `pdfplumber_table_extractor.py:180, 216, 237-245, 483-520`; `structured_table_extractor.py:449-471` |
| 26 | B-6-13 | low | pdfmux dead code (and it would process the whole PDF per table if enabled) | `pdfmux_router.py:157-160`; `parsing_config.yaml:167-168` |
| 27 | B-6-14 | low | `ContextualCaptionService` never fires (content is a path) | `contextual_caption_service.py:71-87` |
| 28 | B-6-17 | low | Phase 6 figure and corpus counters count non-existent types | `main.py:899-903, 920-931` |
| 29 | B-7.5-03 | low | 7.5 thresholds hard-coded; the parallel runner passes different flags | `hierarchy_enricher.py:860-907`; `parallel_runner.py:236` |
| 30 | B-5-03 | low (latent) | Only the first Docling provenance kept; 0 multi-provenance items found in OD pp.20–50 | `layout_analysis_service.py:253` |

**Suggested fix order** (by impact and risk):
1. B-7.5-01 items (1), (2), (5) and (7), plus B-7-01 (a): they fix the structural damage.
2. B-5-01 and B-6-16 together: labels, captions, footnotes and filter exemptions. Across 8 traced reports this recovers 148 unit lines, 81 source lines, 45 captions and chapter titles, and about 80 section headings.
3. B-6-04: one-line markdown normalisation plus the table exemption.
4. B-6-05, the vertical-text words fix.
5. B-6-09 and B-6-10 on table structure.
6. B-6-18 and B-6-15 for charts.
7. The rest.

## Appendix: element-trace harness results (current code, Phases 5 and 6)

`step2/B/trace_harness.py` runs the real `LayoutAnalysisService` and `ContentExtractionService` (MPS, Docling 2.74) and records every block's route, extraction method and garbage-filter verdict. The outputs are `step2/B/trace_<report>.json`, and `summarize_traces.py` categorises the drops. No block failed extraction in any report (0 `None` results besides P2-18). **All loss happens in the garbage filter.**

| Report | Blocks | Dropped | Unit lines "(₹ in crore)" | Source/Note lines | Captions (Table/Chart/Figure/Appendix/Picture) | Chapter titles | Duplicate headers | Tables | Other short text |
|---|---|---|---|---|---|---|---|---|---|
| 2025_08 (GPU) | 910 | 46 | 2 | 0 | 11 | 6 | 4 ("Recommendations") | 1 | 22 |
| OD_2025_05 | 1268 | 69 | 3 | 38 | 5 | 0 | 0 | 0 | 23 |
| JH_2025_02 | 1282 | 98 | **55** | 10 | 3 | 0 | 0 | 0 | 30 |
| BR_2024_03 | 1890 | 122 | 17 | 20 | 8 | 1 | 4 ("Recommendation") | 0 | 72 |
| HP_2022 | 1153 | 127 | **42** | 0 | 0 | 0 | **47** ("Gram Panchayats", "Panchayat Samitis") | 0 | 38 |
| HP_2019 | 716 | 58 | 18 | 2 | 0 | 0 | 22 | 0 | 16 |
| KA_2022_06 | 813 | 45 | 11 | 7 | 10 | 0 | 5 ("Conclusion", "Recommendations") | 0 | 12 |
| 2023_19 | 1995 | 83 | 0 | 4 | 1 | 0 | 24 (running header "Report No.19 of 2023", correct) | 1 | 53 |

"Other short text" is mostly running headers, page labels and signature lines, which is correct to drop, plus some photo captions.
- **Unit lines:** 148 dropped across 7 reports.
- **Source and note lines:** 81.
- **Captions and chapter titles:** 45.
- **Real section headings dropped as duplicates:** about 80.
- **Tables:** 2.
