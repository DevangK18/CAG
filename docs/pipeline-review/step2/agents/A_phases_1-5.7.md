# Agent A: Phases 1–5.7 (manifest, triage, OCR, scaffolding, TOC)

Status: COMPLETE (2026-09-27).

Scratch folder: `scratchpad/step2/A/`. Scripts are listed in the work log.

## Work log

**Files read in full**

| File | Lines | Notes |
|---|---|---|
| `manifest_ingestion_service.py` | 1099 | |
| `triage_service.py` | 211 | |
| `ocr_service.py` | 269 | |
| `ocr_normalizer.py` | 120 | |
| `scaffolding_service.py` | 1470 | |
| `printed_toc_parser.py` | 324 | |
| `toc_quality.py` | 93 | |
| `toc_reconciliation_service.py` | 852 | |
| `toc_llm_validator.py` | 401 | |
| `report_type_profiles.py` | 431 | |
| `excel_analysis.py` | 35 | |
| `toc_table_parser.py` | 496 | Read to the end. It has no importer anywhere, so it is dead code. |

**Call sites and config read**
- `main.py:186-560` (run, Phases 1–3, cache).
- `main.py:593-843` (Phases 4–5.7).
- `parallel_runner.py:150-300`.
- `parsing_config.yaml:1-160`.
- `data_contracts.TOCQualityMetrics`.
- `gemini_client.generate_with_retry`.
- `run-parsing.yml`, the GCS sync lines only.

**Evidence sources**
- Run logs 35994256570, 36167161942, 36191270703, and `runs-gpu` 36194014772.
- The CG OCR output `audit/gcs/processed/ocred/CG_…_ocred.pdf`.

**Scripts**
- `step2/A/toc_gates.py`: runs every Phase 4 TOC source (bookmarks, printed contents, heuristic) and the real `build_scaffold` on all 26 PDFs. It records which quality gate accepts each source. Output: `toc_gates.json`.
- Ad-hoc inspection:
  - bookmarks of HP_2022, KA, JH, BR, 2023_11 and 2025_38;
  - printed-contents rows vs parsed entries for OD, JH, HP_2019 and HP_2022;
  - page headers and footers of HP_2022;
  - CG OCR output metadata.
- `step2/A/printed_toc_defects.py`: counts the printed-contents parser defect classes across all 26 PDFs (A-4-01).
- `step2/A/supplement_precision.py`: classifies the headings Phase 5.5 added (final parents minus the Phase 4 TOC) and simulates the stricter admission rule (A-5.5-01). Output: `supplement_precision.json`.
- Inline scratch runs, all verified by running:
  - `assess_toc_quality` on every final parent list (A-TQ-01, A-5.5-02);
  - `TOCLLMValidator._convert_page_numbers` with the production page map vs `build_printed_page_map` (A-5.7-02);
  - page-number detection with the current regex vs a band plus "N | Page" pattern on all 26 PDFs (A-4-03, A-4-06);
  - `_generate_heuristic_toc` with a forced exception (A-4-05);
  - a PyMuPDF block scan of OD pp. 30/35/43 for heading order (A-5.5-04).
- Everything else is marked "verified by reading" in each issue.

---

## Phases 1–3: Manifest, triage, OCR

### Data flow
1. **Manifest load.** `main._phases_1_to_3` (`main.py:231`) runs `ManifestIngestionService.process_manifest` (`manifest_ingestion_service.py:1048`). This calls `load_manifest` (:202), which works in four steps:
   - detects the tier from the filename (:221);
   - reads the Excel file, with a header-row heuristic (:240-251);
   - renames columns (:259-288);
   - overrides the tier from the Government Type column (:291-312), then cleans the metadata (:360).
2. **Per row** (:1064-1066, sequential), `_download_pdf` (:900):
   - builds the report ID (:687);
   - resolves an existing PDF: exact name, then legacy zero-pad name, then Original Title name (:941-961);
   - otherwise downloads the PDF.
3. **Report filter.** `--reports` is applied only afterwards (`main.py:245-249`), as an exact match on the ID.
4. **Cache check** (`main.py:399-431`). The key is `data/raw/.cache/{report_id}_triage.json`, plus `_ocr.json` for scanned reports.
5. **Uncached tasks** go through `_process_new_tasks` (`main.py:456`):
   - `TriageService.triage_document` (`triage_service.py:58`): median non-blank chars per page over 10 pages, starting at page 10;
   - `OCRService.ocr_document` (`ocr_service.py:53`), which calls `ocrmypdf` through `subprocess.run(timeout=600)`.
6. **Output:** `state.successful_triaged`, which contains the cached tasks plus native tasks plus OCR successes.

On the VM, `run-parsing.yml:190-191` rsyncs all of `raw/` and `processed/` (including `.cache` and `ocred/`) down before each run. So ingestion "finds" every PDF locally, and the triage cache persists across runs.

### Does it run?
- **Tier override:** runs and works. The local run logs `overridden by column: local_body`.
- **Report ID:** works for union, state and local. ATIR IDs never happen (A-1-03).
- **Download:** not exercised on the VM. Every PDF resolved from the rsynced `raw/` (8× "Found PDF with Original Title" in the local run).
- **Triage:** ran in the state and local runs (4 native, 1 scanned). The union run used the cache for 19/19.
- **OCR:** ran once (CG) and failed on the timeout (A-3-01).

### Issues

#### A-3-01 · high · The OCR timeout discards a finished output, and 600 s is a fixed value
- **Location:**
  - `ocr_service.py:113-116, 166-174, 213-228` (`subprocess.run(..., timeout=self.timeout)`);
  - `parsing_config.yaml:35-41` (`timeout: 600`, `output_type: "pdfa"`);
  - `main.py:500-514`.
- **Root cause:**
  - The whole `ocrmypdf` run is one blocking call with a fixed 600 s limit that doesn't depend on page count.
  - On `TimeoutExpired`, the task is marked `failed_ocr`, and the output file is never checked.
  - No path reuses an OCR'd PDF that already exists in `data/processed/ocred/`, which is rsynced from GCS on the VM. A rerun of CG repeats the OCR from scratch and times out again.
- **Explains Step 1:** P1-01.
- **Evidence:**
  - `CG_…_ocred.pdf` is a complete PDF/A-2B: `pdfaid:part="2" conformance="B"`, creator `OCRmyPDF 16.13.0 / Tesseract 5.5.0`, producer pikepdf, 129 pages.
  - Only 10 pages have no text, and those are photo pages.
  - The metadata `modDate` is 21:58:27. OCR started at about 21:51:07 (the 22:01:07 TOCRejection line is logged immediately after the 600 s timeout).
  - So ocrmypdf had run the whole pipeline, including the PDF/A metadata step, at about 440 s. It was then killed at 600 s, either during the final optimise/copy step or while waiting for child processes to close stdout/stderr (`capture_output=True`).
  - The measured throughput is about 3.4 s/page for OCR plus about 1–2 min of PDF/A and optimise on an e2-standard-4.
- **Fix proposal:**
  1. Set `timeout = max(config.timeout, pages * config.timeout_per_page)`, with `timeout_per_page: 8` on CPU. This mirrors `layout.conversion_timeout_per_page`. 129 pages would get 1032 s.
  2. Before OCR, reuse `ocred/{id}_ocred.pdf` if it opens and has a text layer on at least 50% of its non-image pages (mark it `ocr_complete` and write the cache).
  3. On `TimeoutExpired`, do the same check before failing.
  4. Set `output_type: pdf` and add `--optimize 0`. Nothing downstream needs PDF/A, and the Ghostscript PDF/A pass is the slowest and most fragile step for image-heavy scans.
  5. Pass `--jobs <cpu_count>` explicitly and add `--rotate-pages --deskew` for scans. The last one is an improvement, not a fix.
- **Risk / effort:** low / S.
- **Confidence:** the file state was verified by inspection. The exact reason ocrmypdf was still alive at 600 s is inferred.

#### A-3-02 · medium · OCR failures are invisible: the module has no logger, and the console prints a check mark
- **Location:**
  - `ocr_service.py:1-8`: no `import logging` or `logger`.
  - `ocr_service.py:166-178`: errors go only to `task.error_log` and the no-op trace emitter.
  - `main.py:516-518`: `✓ OCR: 0/1 successful`.
  - `main.py:507-514`: the failure is appended to `state.failed["ocr"]` but never logged.
- **Root cause:**
  - Failures are recorded only in the task and in trace red flags, and trace is off in production (no `--trace`).
  - Also, `_validate_ocr_output` (:141-146) failing leaves `processing_status = "ocr_complete"`, so a corrupt output passes as success.
  - Native documents get "Document not classified as scanned, skipping OCR" appended to `error_log` (:68). That is noise in an error log.
- **Explains Step 1:** P1-02.
- **Evidence:** the local log has no ERROR or WARNING line for CG; lines 112-114 are `[1/1] OCR CG…`, `✓ OCR: 0/1 successful`, `✓ 4/5 reports ready`.
- **Fix proposal:**
  - Add a module logger. Log `logger.error(f"[{id}] OCR failed: …")` on every failure branch, including the stderr tail.
  - Set `failed_ocr` when validation fails.
  - In `main`, print `✗` when the success count is below the total.
- **Risk / effort:** none / S.
- **Confidence:** verified by reading and from the log.

#### A-1-01 · medium · A run that selects 0 reports, or loses any, still ends "success"
This covers only the Phases 1–3 part of P1-03.
- **Location:**
  - `main.py:245-249`: the filter is an exact ID match, and a miss is silent.
  - `main.py:193-197`: "No documents ready… terminating" then a bare `return`.
  - `main.py:240-242`: a manifest exception is logged and the function returns.
  - All three lead to process exit 0.
- **Root cause:** `run()` has no failure accounting and never sets a non-zero exit. Requested IDs that match nothing are not reported. The rest of the exit path (final summary, exit code, workflow status) is Agent C's.
- **Explains Step 1:** P1-03, and the earlier local run 36187916885 that filtered to 0 and still succeeded.
- **Fix proposal:**
  - After filtering, compute `missing = set(report_filter) - {t.report_id}`. If it's non-empty, log an ERROR listing the missing IDs and the closest ID for each (`difflib.get_close_matches`).
  - Exit with a non-zero code when 0 tasks remain, or when manifest ingestion raises.
  - Hand-off to Agent C: propagate any failed report into the exit code and status.
- **Risk / effort:** low / S.
- **Confidence:** verified by reading.

#### A-1-02 · low · Every manifest row is resolved or downloaded, sequentially, before the filter
- **Location:**
  - `manifest_ingestion_service.py:1064-1066`: sequential `await` per row. The `httpx.Limits(max_connections=5)` at :1062 has no effect.
  - `main.py:245`: the filter runs afterwards.
- **Root cause:** the filter isn't passed into `process_manifest`. On the VM the cost is hidden because `raw/` is rsynced first, so every row resolves locally. Locally, or for a new manifest, every PDF would be downloaded.
- **Explains Step 1:** P1-06. The "8 downloads successful" in the log were really 8 local resolutions.
- **Fix proposal:**
  - Pass `report_filter` into `process_manifest`, build the IDs first (`_build_report_id` is pure), and only resolve or download matching rows.
  - Download with `asyncio.gather` under a semaphore of 5.
- **Risk / effort:** low / S.

#### A-1-03 · medium · ATIRs are never detected: the ID, audit category, report type and Phase 9 profile are all wrong
- **Location:**
  - `manifest_ingestion_service.py:727-729`: ATIR only if the `Audit Category` column says "atir".
  - `manifest_ingestion_service.py:671-679`: without that column, the category is inferred from `Report Type`.
  - `manifest_ingestion_service.py:151-174`: `infer_audit_category_from_report_type` has no ATIR branch and defaults to "compliance".
  - `report_type_profiles.py:203-267`: `detect_report_type` has an ATIR rule, but it reads `metadata["report_title"]` and `metadata["report_type"]`, keys that `_build_metadata` never sets (it sets "Title" and "Report Type"). It also expects TOC entries as dicts (:337-339) when they are lists.
  - `detect_report_type` is never called in production: `main.py:1269` and `parallel_runner.py:275` call `enrich_document` without `task=`, so `semantic_enrichment_service.py:159-164` falls back to `normalize_report_type(report_metadata["report_type"])`, which gives "Compliance Audit" → compliance.
- **Root cause:**
  - The local manifest has no Audit Category column (the columns logged are `['Report No','Ministry','Report Type','Sector','Date','State Name']`).
  - The title-based fallback in `report_type_profiles` is unreachable, and would read the wrong keys even if it were reached.
  - So the `atir`, `state_commercial` and `state_performance` profiles are dead code in production.
- **Explains Step 1:** P1-05, and the "ATIR typed compliance" item in P9-01. Log evidence: `Detected report type: compliance` for both HP reports.
- **Fix proposal (design):** detect ATIR in one place, `manifest_ingestion_service._build_metadata`, and store it as `audit_category="atir"`. Precedence:
  1. The explicit `Audit Category` column, when present.
  2. The title (Original or Recommended): `r"\bannual\s+technical\s+inspection\b|\bATIR\b|\bATI\s+report\b"`, case-insensitive. This matches all three HP titles in the manifest ("Annual Technical Inspection Report…", "ATI report on…").
  3. For local body reports with no hit, the cover-page text as a fallback: first 2 pages, the same regex. This is a cheap fitz read, done after the PDF is resolved.

  Then:
  - `_build_report_id` reads the computed category rather than the raw column (:728). That gives `HP_ATIR_2019_…`.
  - The year for ATIR IDs should come from the title's "Report of 2017" or the cover's "for the year(s) 2017-18 and 2018-19". The Date column gives the publication year, the same data issue as P1-08.
  - `report_type_profiles.detect_report_type` should read `Title` / `Report Type` / `audit_category`, or better be passed `report_metadata`. Hand-off to Agent C: pass `task=task` at `main.py:1269` and `parallel_runner.py:275`.
  - Fix `_detect_from_toc` to accept list entries.
- **Risk / effort:** medium, because changing IDs changes output filenames and makes old outputs orphans in GCS. Effort M.
- **Confidence:** verified by reading and from the log.

#### A-1-04 · low · The triage cache is keyed only by report ID, and a cache hit can silently drop the OCR'd PDF
- **Location:**
  - `main.py:399-431`: the key is the report ID only.
  - `main.py:538-548`: the cache stores `{classification, timestamp}` only.
  - `main.py:443-452`: for a cached "scanned" task, `ocr_complete` is set even if `ocred/{id}_ocred.pdf` does not exist, so `_get_pdf_path` quietly uses the image-only original.
- **Root cause:** the cache doesn't record the PDF's size, mtime or hash, or the triage config (`text_threshold`, sample pages). A replaced PDF, or a changed threshold, keeps the stale classification forever. Because `.cache` is rsynced to GCS, this persists across VMs.
- **Explains Step 1:** P1-07.
- **Fix proposal:**
  - Store `{classification, pdf_sha1 (or size+mtime), text_threshold, sample_pages}` and invalidate on mismatch.
  - For scanned reports, treat the cache as valid only if the OCR'd PDF exists and has text.
- **Risk / effort:** low / S.

#### A-1-05 · low · The tier is decided from the first non-null Government Type value only
- **Location:** `manifest_ingestion_service.py:291-303`.
- **Root cause:** a manifest that mixes tiers is processed wholly as the first row's tier: the raw directory, the ID format and the metadata for every row. Every other row's value is ignored without a warning. This is latent: current manifests are single-tier.
- **Fix proposal:** warn if more than one distinct tier appears. Better, make `government_body_type` per row (it is already stored per task in `_build_metadata`), including the raw directory.
- **Risk / effort:** low / M.

#### A-1-06 · low · Minor defects found by reading
- `_download_pdf` has `@retry(stop_after_attempt(3))` (:897), but the body catches every exception (:1028) and returns a failed task, so the retry never fires. It can also leave a partial file at `local_path` that later counts as "exact" found (:941). **Fix:** re-raise inside, catch outside, and write to `.part` then rename.
- `detect_government_body_type` (:103-130): a filename containing "state" and "union" returns union. Harmless now that the column overrides it.
- `format_report_no` (:388): `"of" in val.lower()` matches any value that contains "of" (for example "Report of 2017"). The raw string is kept, and `_build_report_id` then falls to its generic branch. This is how HP_2019 got the ID year 2019 from the Date column and no number (P1-08).
- The trace emits `tier_detection` "Detected from manifest filename pattern" for every task (`main.py:281-287`), even when the column decided the tier. The trace text is misleading; trace is off in production.
- `excel_analysis.py`: a debug utility that logs through a logger that is never configured, so running it as `__main__` prints nothing. No callers.
- `triage_service.py`: correct and robust (median, blank-skip, start at p10). One latent gap: an image-only report whose pages carry only a running header of 150 or more chars is classified native. A per-page image-coverage check would catch it (`page.get_images` covering more than 80% of the page area with fewer than 300 chars). CG classified correctly (1 text page).

### Improvements (not bugs)
- **A per-report status file:** write `data/processed/status/{id}.json` holding the phase reached, the error and the duration. It gives the workflow a report-level pass/fail without parsing logs (hand-off to Agent C).
- **OCR language:** `ocr.language: "eng"`. Local and state scans can have Hindi pages; Dockerfile.parsing installs only `tesseract-ocr-eng`. Use `eng+hin` if Hindi reports enter the corpus. Otherwise Devanagari becomes garbage that the TOC filters then have to reject.

### Wired-and-working inventory (Phases 1–3)
| Component / flag | Status | Evidence |
|---|---|---|
| Tier from the filename | Works but is superseded | The log line "Detected… union" is always overridden on the VM |
| Tier from the Government Type column | Works | `overridden by column: local_body` |
| Report ID builder, union/state | Works | IDs in the output |
| Report ID builder, ATIR branch | Never runs | No Audit Category column (A-1-03) |
| Legacy zero-pad / Original Title PDF fallback | Works | 8× "Found PDF with Original Title" |
| HTTP download + tenacity retry | Retry never fires (A-1-06); download not exercised on the VM | Code |
| `--reports` filter | Works; silent on a miss | A-1-01 |
| Triage cache | Works, but is keyed only by ID | A-1-04 |
| `TriageService` | Works | 4 native, 1 scanned, both correct |
| OCR (`ocrmypdf`) | Runs but broken for 100+ page scans | A-3-01 |
| OCR output validation | Result ignored | `ocr_service.py:141-146` |
| `triage.sample_pages`, `text_threshold`, `ocr.*` config | Read | `config.py` via `get_config()` |
| `ocr.force_ocr: true` | Read, and needed: CG has 1 text page, and without the flag ocrmypdf aborts with PriorOcrFound | |
| `excel_analysis.py` | Dead utility | No importer |

---

## Phase 4: Scaffolding (TOC and page map)

### Data flow
`ScaffoldingService.build_scaffold` (`scaffolding_service.py:430`) runs the TOC sources in a fixed order, and the first one accepted wins:

1. **Bookmarks** (`_extract_embedded_toc`, :637). They are scored by `_score_embedded_toc` (:734) and `TOCQualityMetrics.score()` (`data_contracts.py:58-90`), and accepted if the score is at least `bookmark_quality_threshold*100` = 60.
2. **Printed contents page** (:483-503, `printed_toc_parser.parse_printed_toc`). Accepted if it has at least 5 entries and `min(assess_toc_quality, verified%)` is at least 60.
3. **Heuristic headings** (:506-523, `_generate_heuristic_toc`): font-size and position scoring over the first 100 pages, with levels from font-size quantiles.

After that:
- The page map is built (:546, `_build_page_mappings`).
- The TOC is deduplicated: `_dedupe_trusted_toc` for bookmarks and printed TOCs, `_filter_and_dedupe_toc` for heuristic ones.
- Output: `task.scaffold = {toc: [[level, title, physical_page]], page_map: {physical: label}, heading_positions (heuristic only), toc_method, toc_quality}`.

### Does it run? (`step2/A/toc_gates.py` on all 26 PDFs, current code)

| Source chosen | Reports |
|---|---|
| Printed contents | 17: all 13 remaining union, OD, JH, BR, 2025_06 |
| Bookmarks | 6: 2024_01, 2025_03, 2025_04, 2025_16, 2025_18 (real Word-generated bookmarks, scores 93–95); **HP_2022 (70.7) and KA (63.7), both junk** |
| Heuristic | HP_2019 |
| None | CG (scanned source) |

- **Bookmark scores:**
  - JH scored 53.4 (rejected, correctly). BR scored 12.1, 2023_11 46.5 and 2025_38 28.7 (all rejected, correctly).
  - KA's printed contents would have scored 97, with 82 entries and 98% verified. It was never used, because junk bookmarks won first.
- **Union printed contents:**
  - 2020_16, 2023_19, 2025_08 and 2025_38 have 8–13 entries each.
  - The FRBM and Accounts reports would give 7, but those use real bookmarks.
  - This is correct: these contents pages list chapters only. So the union section structure depends entirely on Phase 5.5.

### Issues

#### A-4-01 · high · The printed-contents parser mishandles the three-column (Title | Para | Page) layout used by every state and local report
- **Location:** `printed_toc_parser.py:98-136` (`_parse_rows`); :30-38 (`ENTRY_START_RE`, `PAGE_TAIL_RE`); :29 (`RUNNING_HEADER_RE`); :24-28 (`HEADER_WORDS`); :139-150 (`_level`).
- **Root cause.** Five mechanisms, each reproduced with `_page_rows` / `_parse_rows` on the real PDFs:
  1. **The para number stays in the title.** `PAGE_TAIL_RE` peels off only the last number (the page). The para-number column ("1.2", "2.3.1") stays at the end of the body.
     - Example: OD row `Audit objectives 1.2 3` becomes `("Audit objectives 1.2", "3")`.
     - `NUMBERED_RE` / `_level` look for the number at the start, so these entries get the "unnumbered" level.
  2. **The chapter merges with its first section.** A chapter row with no page ("Chapter-1", "Introduction") is kept in `pending`. The next row "Introduction 1.1 1-3" doesn't match `ENTRY_START_RE`, which needs a leading number, so :119-121 prefixes the pending text.
     - Result: `Chapter-1 Introduction Introduction 1.1`.
     - Roman-numeral chapter rows ("I AN OVERVIEW OF …", "II COMPLIANCE AUDIT") aren't recognised as chapters at all. `CHAPTER_RE` wants "chapter" or "part".
  3. **Vertically centred multi-line cells are shifted by one.** When a title's first line prints above the label/page row and the second line below it:
     - JH: "Summarised financial position…" / `Appendix 2.3 108` / "as on 31.03.2024".
     - 2025_08 union: "Ocean Observation Network – Deployment and" / `Chapter III 17-33` / "Maintenance of Platforms".
     - Branch :114-117 appends the line above to the *previous* entry, and the line below starts the *next* entry.
     - Result: `Chapter II Management of … Ocean Observation Network – Deployment and`, `Chapter III Maintenance of Platforms`.
  4. **Continuation-page headers are glued in.** A running header "Audit Report (Local Government) for the year ended March 2022" and a repeated column header "Reference to / CHAPTER DESCRIPTION / Paragraphs Page" are glued into the next entry. `RUNNING_HEADER_RE` only knows "Report No. N of YYYY", and "Reference to" contains "to", which is not in `HEADER_WORDS`.
  5. **Appendix rows lose their appendix type.** BR's "4.1 Avoidable expenditure … 4.1 137" (the appendix number first, the referenced para second) is parsed as section 4.1 at depth 2 under "Appendices". So BR's appendices become duplicate "4.1 / 5.1 …" sections on pp. 137+, with no "Appendix" parents. This is the root cause of the annexure-link failure P9-09 for BR.
- **Measured defects** (`printed_toc_defects.py`, all 26):

  | Report | Entries | Para no. in title | Chapter merged with section | Header glued in |
  |---|---|---|---|---|
  | OD | 55 | 50 | 9 | — |
  | JH | 91 | 83 | 4 | 2 |
  | BR | 58 | 36 | 3 | 3 |
  | HP_2022 | 66 | 50 | 4 | — |
  | HP_2019 | 54 | 33 | 4 | — |
  | Union | — | 0–10 each (2023_07: 10; the other 18: 0–3) | — | — |

- **Explains Step 1:** P4-01 in full, P4-03 in part (A-5.5-03), P9-09 for BR, and part of P7-02. When the parser loses the section number, Docling's "2.1 Deficiencies in Planning" can't be matched to "…Deficiencies in Planning 2.1", so it is added a second time.
- **Why verification didn't catch it:** `_verify_on_pages` (:302-324) counts an entry as verified if its mapped page prints the right page number, or the title text appears nearby. Neither checks structure. OD is "100% verified" with 9 merged chapters.
- **Fix proposal** (`_parse_rows` rewrite, still row-based):
  - After `PAGE_TAIL_RE`, strip a trailing para token `\s(\d+(?:\.\d+)+(?:\s*\([A-Za-z]\))?)$` and prepend it as the section number: `"1.2 Audit objectives"`. Also accept a leading appendix/annexure number followed by a trailing para reference, BR style: `^(\d+(\.\d+)*(\s*\([A-Z]\))?)\s+(.+?)\s+(\d+(\.\d+)+)$` inside an Appendices block, giving `"Appendix 4.1 …"`.
  - Treat pending rows as a chapter heading and flush them as their own entry when:
    - they match `CHAPTER_RE`, a roman chapter `^[IVX]+\s+[A-Z]`, `PART[-\s][A-Z]`, or are all capitals;
    - and the next row carries a para number.
  - Assign orphan lines to the page row with the smaller vertical gap, using the row y-coordinates already computed in `_page_rows` (return `(y, text)`). On a tie: a lowercase start goes to the previous entry, otherwise to the next. This fixes both the JH/2025_08 centred cells and the OD "education" tail.
  - Drop rows that repeat identically on two or more contents pages (running header and column header), plus the lone page numeral ("ii").
  - Add a structural check to `confidence`: the share of entries whose title (not number) is found near the mapped page. Penalise titles containing a chapter keyword followed by a section number.
- **Risk / effort:** medium, since it changes the TOC of every state and local report. Guard with fixtures from OD, JH, BR, HP_2019, HP_2022, 2025_08 and 2023_19 (the rows are already captured in this investigation). Effort M.
- **Confidence:** verified by running the parser on the real PDFs.

#### A-4-02 · high · PDF-merger bookmarks pass the quality gate because the score measures shape, not content; and bookmarks are tried before a better printed contents page
- **Location:**
  - `scaffolding_service.py:734-825` (`_score_embedded_toc`);
  - `data_contracts.py:58-90` (`score()`);
  - `parsing_config.yaml:62-68` (`assembly_bookmark_patterns`);
  - `scaffolding_service.py:476-483`: the order; printed contents are tried only if bookmarks were rejected.
- **Root cause:**
  - `score()` is structural:
    - 2 points per entry, up to 30;
    - 8 per level, up to 25;
    - +15 if any title contains "chapter";
    - +15 for numbered sections;
    - coverage.
  - The only content penalty is `assembly_bookmark_patterns`, which needs *two* digits and a space (`^\d{2}\s+\w+`).
    - JH was rejected only because 6 of its 20 bookmarks happen to be numbered 10–15 ("10 separator_Chapter 3"), giving confidence 0.85 and a score of 53.4.
    - HP_2022 ("1 Cover pages", "2 TOC", "5 Chapter 1 HP ATIR", 17× "Blank Page", "Binder1.pdf") numbers its files 1–9. Result: confidence 1.0; 43 entries → 30 points; 3 levels → 24; "chapter" → 15; total 70.7.
    - KA ("1. Nagarothana Front Page English", "3. Table of Contents", "10. Appendix Median", "AGS ENG COVER.pdf", "Page 1") uses "N." with a dot. Result: 22 entries, 2 levels, "chapter", total 63.7.
  - Nothing looks at "Blank Page", `.pdf`, "Cover", "separator", "Page N", or bookmarks whose targets are all page 1. In HP_2022, 30 of 43 bookmarks target page 1 or -1.
  - Printed contents are only considered after bookmarks fail. KA's printed contents (82 entries, 98% verified, quality 97) were never reached.
- **Explains Step 1:** P4-02. The HP_2022 and KA junk L1s, and part of P4-03 (KA `6.Chapter 1-Introduction` + `Chapter-I`).
- **Fix proposal:**
  1. Add a bookmark junk filter before scoring:
     - drop titles matching `(?i)^blank page$|\.pdf$|^page \d+$|^binder\d*|cover|separator|inner head|back page|_english`;
     - strip a leading file-order prefix `^\d{1,2}\s*[._-]?\s*`;
     - reject the bookmark set if more than 30% of entries were junk, or if more than 30% target page ≤1 or the same page.
  2. Choose by content, not order:
     - compute all three candidates;
     - prefer printed contents whenever they are verified at 0.8 or more with at least 5 entries (the author's own structure);
     - use bookmarks only if there are no printed contents, or if the bookmarks agree with them (at least 70% of the printed chapter titles are found among the bookmark titles);
     - use the heuristic last.
  3. Replace `score()` with the content-aware `assess_toc_quality` (after A-TQ-01), plus the junk ratio.
- **Risk / effort:** low for the five real-bookmark FRBM/Accounts reports: their printed contents have 7 entries, so the rule has to let a much richer bookmark set that agrees with them win. Effort S–M.
- **Confidence:** verified by running on all 26 PDFs.

#### A-4-03 · medium · Page numbers printed as "N | P a g e" are not recognised, so ATIR printed contents fail verification and the page map is built from footnote markers
- **Location:** `printed_toc_parser.py:153-172` (`build_printed_page_map`): `re.fullmatch(r"\d{1,3}", line)` over the first and last 4 lines.
- **Root cause:**
  - HP reports print "12 | P a g e". That line never matches.
  - Instead, footnote markers ("1", "2", "3" as lone lines near the page bottom) are read as page numbers. HP_2022 gets labels 1, 2, 1, 2, 5, 6, 14… on pages 18, 22, 31, 33… Only 24 of 142 pages are labelled, and the dominant offset covers only 3 pages.
  - So `_to_physical` maps entries to wrong pages, and verification is 18% (HP_2022) or 35% (HP_2019). Both printed contents are rejected, leaving junk bookmarks (HP_2022) or a broken heuristic TOC (HP_2019).
- **Explains Step 1:** the review-list items "HP_2019 printed TOC verified 35%" and "HP_2022 18%", then P4-02 and P4-03 for HP.
- **Evidence:** HP_2022 page 18 head is `['1 | P a g e', 'PART-A', …]`, tail `[…, '1', 'Stated by Director…']`. Adding a "N | P a g e" pattern and restricting to top/bottom bands raises the labelled pages from 24 to 111 (HP_2022) and from 19 to 67 (HP_2019). Script: inline in the work log; the results are in the table below.
- **Fix proposal:**
  - Accept `^(\d{1,3})\s*\|\s*P\s*a\s*g\s*e$`, `^Page\s+(\d+)(\s+of\s+\d+)?$` and `^[-–]\s*(\d+)\s*[-–]$`.
  - Read only text blocks in the top or bottom 8% of the page.
  - Reject a candidate label that breaks a run: keep labels that agree with an offset shared by at least 3 neighbouring pages. This drops footnote markers.
- **Risk / effort:** low / S.
- **Confidence:** verified by running.

#### A-4-04 · medium · The heuristic TOC splits multi-line chapter banners and accepts table rows
- **Location:**
  - `scaffolding_service.py:1112-1179`: one `TextBlock` per PyMuPDF block.
  - :1228-1287: each block is scored independently.
  - :1397-1430: no merging of adjacent candidates.
  - :259-324: the reject patterns miss "Total (iii) 1,00,000 …".
- **Root cause:**
  - A chapter banner set as three separate blocks becomes three L1 entries.
    - HP_2019: `Chapter-1` / `Profile of Panchayati Raj` / `Institutions`, all on page 11. The same happens for chapters 2 and 4.
  - Table cells in large or bold fonts on appendix pages become headings: `Municipal Council, Chamba (\` in lakh) Sl. No`, `Total (iii) 1,00,000 4. Sh. Victor Bhisty`.
  - The heuristic TOC has 21 entries and no sections, yet `assess_toc_quality` gives it 100 (A-TQ-01).
- **Explains Step 1:** P4-03 (HP_2019 split L1s) and P7-02 (HP_2019, 34.7% wrong-parent).
- **Fix proposal:**
  - Merge consecutive candidates on the same page that have the same rounded font size and a vertical gap under 1.5× the line height.
  - Skip blocks inside table regions: `page.find_tables()`, or blocks with 2 or more numbers.
  - With A-4-03 fixed, HP_2019 would use its printed contents anyway.
- **Risk / effort:** low / S.

#### A-4-05 · high (latent) · The heuristic TOC's error handler raises `AttributeError`, which turns a heuristic failure into a whole-report scaffolding failure
- **Location:** `scaffolding_service.py:1108-1110`: `self.logger.error(...)`, but `ScaffoldingService` has no `logger` attribute. The module-level `logger` exists at :41.
- **Root cause:** any exception inside heuristic generation (a malformed page or font dict) raises `AttributeError` from the `except` block. `build_scaffold` catches that at :608 and marks the report `failed_scaffold`. The report is then dropped for good, even though page mapping and later phases could proceed.
- **Evidence:** a scratch run with `_extract_text_blocks` monkeypatched to raise gives `AttributeError: 'ScaffoldingService' object has no attribute 'logger'`.
- **Explains Step 1:** latent; not triggered by the audited reports.
- **Fix:** use `logger.error(..., exc_info=True)`.
- **Risk / effort:** none / XS.
- **Confidence:** verified by running.

#### A-4-06 · medium–high · The page map is PDF page labels or physical+1, never the printed page number (the Phase 4 part of P8-03)
- **Location:** `scaffolding_service.py:1436-1451` (`_build_page_mappings`). Consumed at `chunking_service.py:576-577, 620-622, 670` (Agent B).
- **Root cause:** `page.get_label()` is used when the PDF defines page labels. Only 3/26 PDFs do: BR, 2025_26 and 2025_35, exactly the three Step 1 found matching. Otherwise the code uses `str(page_num + 1)`. A parser for printed page numbers already exists (`build_printed_page_map`), but it's used only to place printed-contents entries.
- **Explains Step 1:** P8-03 (23/26 reports mismatch on 100% of pages).
- **Evidence:** every union, state and local PDF except those 3 has 0 page labels. For OD, printed page 15 is physical 38, but the map says 15.
- **Fix proposal:** `page_map[i]` should be:
  1. the PDF label if the PDF defines labels;
  2. else the printed arabic or roman number from `build_printed_page_map` (with the A-4-03 fix);
  3. else a value interpolated within a run with the same offset (between two detected pages with equal `i - label`);
  4. else `None`.

  Consumers should display `None` as "unnumbered", not physical+1. This also fixes Phase 5.7's page conversion (A-5.7-02).
- **Risk / effort:** low / S. Agent B's chunking and Agent C's assembly must tolerate `None`.
- **Confidence:** verified by running.

#### A-4-07 · low · Other Phase 4 defects found by reading
- **Heuristic scans only 100 pages** (`_generate_heuristic_toc(max_sample_pages=100)`, :1066). Reports longer than 100 pages that fall to the heuristic lose every heading after page 100. Latent: HP_2019 has 90 pages.
- **Hard-coded page geometry.** `StyleProfile.page_stats` is fixed at A4 portrait with a 72 pt margin (:1217). Heading-position points are wrong for landscape pages and non-A4 layouts.
- **`toc_rejection_alert_threshold` is never read.** `TOCRejectionLogger.ALERT_THRESHOLD = 0.25` is hard-coded (:76), so the config key `scaffolding.toc_rejection_alert_threshold` does nothing. `min_toc_quality_score: 20` and `embedded_toc_min_entries: 3` also appear unused by `ScaffoldingService`: `embed_toc_min_entries` defaults to 5 and is never compared. To confirm, Agent C's `config.py` inventory should show whether they are loaded.
- **Heading positions only for the heuristic path.** For printed and bookmark TOCs, `heading_positions` stays empty until Phase 5.5, so same-page section boundaries depend on Docling fuzzy matches (A-5.5-04).
- **`_bookmark_page` clamps bad targets.** It maps -1 or an out-of-range target to page 0 (:986), so broken bookmarks silently point at the cover.
- **`logs/rejected_toc.log` grows without limit.** It is opened in append mode on every `ScaffoldingService` construction and uploaded to GCS every run (`run-parsing.yml:244`).

### Wired-and-working inventory (Phase 4)
| Component / flag | Status | Evidence |
|---|---|---|
| Bookmark extraction + scoring | Runs but broken: accepts junk (A-4-02) | HP_2022, KA |
| `bookmark_quality_threshold` / `assembly_bookmark_patterns` / `cag_quality_patterns` | Read; patterns too narrow | `toc_gates.py` |
| Printed-contents parser | Works for two-column union contents; broken for three-column state and local ones (A-4-01) | `printed_toc_defects.py` |
| `build_printed_page_map` | Works; fails on "N \| Page" (A-4-03) | HP |
| Heuristic TOC | Runs (HP_2019); splits banners and accepts table rows (A-4-04) | |
| Heuristic error handler | Broken (A-4-05) | scratch test |
| `_build_page_mappings` | Runs but wrong for 23/26 (A-4-06) | |
| TOC rejection logger / alert | Works; the threshold is hard-coded | |
| `toc_rejection_alert_threshold`, `min_toc_quality_score`, `embedded_toc_min_entries` config | Probably never used | A-4-07 |
| `toc_table_parser.py` (Layer 2 "TOCTableParser") | Dead code: no importer | grep |

---

## TOC quality score (`toc_quality.py`), shared by Phases 4, 5.5 and 5.7

#### A-TQ-01 · high · `assess_toc_quality` can't see the defects the audit found, so nearly every TOC scores 85–100
- **Location:** `toc_quality.py:31-46` (`is_garbage_title`), :59-93 (`assess_toc_quality`).
- **Root cause:** the deductions cover:
  - fewer than 5 entries;
  - garbage by `is_garbage_title`: lowercase start, parentheses, fewer than 50% letters, reversed or shifted text;
  - more than 35 L1s;
  - numbered sections at L1 (only when the number is at the *start*);
  - missing chapter numbers;
  - backwards pages;
  - a TOC stopping halfway.

  There are no checks for:
  - junk titles that start with a capital or digit ("Blank Page", "Binder1.pdf", "2 TOC", "5 Chapter 1 HP ATIR");
  - sentences (long, ending in ".", containing ₹ amounts);
  - "Recommendation x.y" boxes, epigraphs, list items;
  - the same chapter repeated;
  - a chapter merged with its section, or a para number at the end of a title;
  - entry density (entries per page);
  - section numbers that don't match their parent chapter;
  - entries that can't be found on their page.
- **Evidence** (the scorer run on the *final* parent lists):
  - HP_2022 = **100** (with "Blank Page", "Binder1.pdf", 45 finding sentences). KA = 100. HP_2019 = 100. OD = 100. GPU 2025_08 = 100.
  - The HP_2019 heuristic TOC (split banners, table rows, no sections) = 100.
- **Explains Step 1:** P5.5-02 and P5.7-01 (together with A-5.5-02), and X-01's garbage-title blind spot.
- **Fix proposal:** a content-based score from 0 to 100. Deduct for:
  - share of junk titles, using the A-4-02 patterns;
  - share of sentence-like titles: more than 14 words; ends with "." and has more than 5 words; contains `₹|\`` plus a number; starts with an enumerator; starts with a quote mark; `^Recommendation`;
  - duplicate chapter numbers;
  - a trailing para number or a chapter merged with a section;
  - share of entries whose title isn't found on its page ±1 (reuse `_verify_on_pages`);
  - density above 1.2 entries per page;
  - L2+ numbers whose chapter prefix doesn't match the enclosing L1.

  `is_garbage_title` should share the same junk and sentence predicates, so that `_normalize_toc` (A-5.5-02) removes these entries too.
- **Risk / effort:** low; it only changes scores and gates. Effort M, including tests.
- **Confidence:** verified by running.


---

## Phase 5.5: TOC reconciliation

### Data flow
`main._phase_toc_reconciliation` (`main.py:707`) calls `TOCReconciliationService.reconcile` (`toc_reconciliation_service.py:113`):
1. **Extract Docling headers** (:295). Every Docling `Section-header` block with confidence ≥ 0.60 has its text clipped from the PDF by bbox, then `_clean_header_title` → OCR normalizer → `_infer_level_from_docling` (pattern, else bbox height).
2. **Noise filter** (:672, `NOISE_PATTERNS`), then **chapter promotion** (:746).
3. **Tier selection** by the Phase 4 `toc_quality`:
   - ≥70 → `_supplement_high_quality` (:473): add every Docling header whose title is under 0.65 `SequenceMatcher` similarity to all existing titles. Level from `_supplement_level`: the number depth, else the enclosing entry's level + 1.
   - 40–69 → `_merge_medium_quality` (:566): add unmatched headers at the Docling-inferred level.
   - <40 or empty → `_prefer_docling_low_quality` (:611): replace the TOC with the Docling headers.
4. `_update_heading_positions` (:640).
5. `_normalize_toc` (:543): drop `is_garbage_title` entries, derive levels from numbering.
6. `_deduplicate_parents` (:714): key = (title, page).
7. **The "keep Phase 4" guard** (:234-241): if the reconciled TOC scores more than 5 below the normalised Phase 4 TOC, keep Phase 4.
8. L1-count and orphan warnings.
9. `toc_quality = min(assess_toc_quality(reconciled), 85)` (:271-272).

### Does it run?
It ran on every report. Post-fix methods:

| Method | Reports |
|---|---|
| supplemented | OD, JH, HP_2022, HP_2019, GPU 2025_08 |
| merged | KA |
| kept_phase4 | BR (its 175 supplemented headers were discarded; BR's 639 parents come from Phase 7.5, Agent B) |

Entry growth: OD 55→170, JH 91→205, HP_2022 26→291, HP_2019 21→170, KA 22→122, GPU 10→120.

### Issues

#### A-5.5-01 · high · Supplementing adds every unmatched Docling `Section-header` with no heading test
This covers recommendation boxes, finding lead sentences, list items, epigraphs, table row labels and appendix-table titles.
- **Location:**
  - `toc_reconciliation_service.py:473-526`: `_supplement_high_quality` adds each unmatched header.
  - :566-609: `_merge_medium_quality` does the same, at the Docling bbox-height level, so junk can land at L1.
  - :48-57: `NOISE_PATTERNS` covers only "(Paragraph…)", "(Source…)", "Report No.", "Page N", "a. ", "(iv) ", digits and dashes. Its `re.IGNORECASE` also makes `^[a-z]\.\s+` reject real "A. Karnataka" subsections.
  - :543-564: `_normalize_toc` drops only `is_garbage_title`, which accepts capitalised sentences.
- **Root cause:**
  - Docling labels anything bold or large as `Section-header`, including recommendation box titles, bold lead-ins, bold table cells and quotes.
  - Nothing checks that the text is a heading: its length, sentence shape, amounts, an enumerator, repetition, being inside a table, or its section number fitting the enclosing chapter.
- **Evidence** (`supplement_precision.py`: added = final parents minus the Phase 4 TOC, classified by rule; "unclear" rows sampled and read):

  | Report | Added | Real (numbered / chapter / front) | Not headings | Unclear |
  |---|---|---|---|---|
  | OD | 115 | 78 | 29 (25 `Recommendation x.y`, 3 sentences, 1 epigraph) | 8 (ES box titles, "Case Study", © line) |
  | JH | 114 | 51 | 9 (6 amount sentences) | 54 (mostly *real* unnumbered sub-heads: "Inflexible expenditure", "Interest payments") |
  | KA | 104 | 74 | 11 (list items) | 19 ("A) GRANTS", "Statement showing…", "Details are given in Appendix 2.12") |
  | HP_2022 | 265 | 115 | 60 (45 finding sentences with ₹) | 90 (mostly table row labels: "Gram Panchayats", "Nagar Panchayats") |
  | HP_2019 | 151 | 73 | 28 | 50 (same kind as HP_2022) |
  | GPU 2025_08 | 110 | 93 | 6 | 11 |

  The numbered sections are the valuable part. For union reports whose contents page lists only chapters, they *are* the section structure.
- **Explains Step 1:** P5.5-01 in full; with A-5.5-03, the P7-03 empty or fragment parents and part of P7-02.
- **Fix proposal: a stricter admission rule for supplemented headers.**
  1. Always admit:
     - numbered sections `^\d+(\.\d+)+\.?\s+[A-Z(‘'"\d]` with at most 20 words and no amount, *whose chapter prefix equals the enclosing chapter's number* and whose numbers ascend within that chapter;
     - chapter, part, annexure and appendix headers not already present by *number*;
     - exact front and back matter.
  2. Admit an unnumbered header only if all of these hold:
     - at most 12 words;
     - no terminal "." or ":";
     - no `₹`/`` ` `` plus a number;
     - not an enumerator `^(\(?[a-z]{1,3}\)|[A-Z]\)|\(?[ivx]+[.)])`;
     - not `^Recommendation`, a quote mark, `Source`, `Note`, `Case study`, `Statement showing`, or `Details of`;
     - its normalised text occurs only once among the report's headers (this rejects the repeated row labels "Gram Panchayats");
     - its bbox is not inside a Docling `Table` block on the same page;
     - its PyMuPDF spans at the bbox are bold, or at least 1 pt larger than the body size.
  3. Put unnumbered admitted headers one level below the *nearest preceding entry on page and y order*, never at L1 unless they match the chapter pattern.

  A simulation of the text-only part (`supplement_precision.py`, "Proposed rule") keeps 77/75/113/75/96 of OD/KA/HP_2022/HP_2019/GPU with ≤3 non-headings each. It wrongly drops "PART A: …", "Appendices", "CHAPTER" and "6.2.3 3D GIS…", which are easy regex fixes. For JH it keeps 47 numbered entries and leaves its real unnumbered sub-heads to the style check (step 2), so the style check is required, not optional.
- **Risk / effort:** medium. It shrinks TOCs, and Agent B's chunking must then attach the paragraphs of dropped pseudo-headings to the surrounding section, which is the desired effect. Effort M.
- **Confidence:** verified by running on the output. The style-check benefit is inferred, because the Docling bboxes are not stored in the output.

#### A-5.5-02 · medium · The reconciled score is a constant: it is capped at 85, computed after garbage removal, and the scorer can't see over-supplementing
- **Location:**
  - `toc_reconciliation_service.py:69-70, 270-272`: `QUALITY_CAP = 85`, `toc_quality = min(new_quality, 85)`.
  - :229 and :237-238: `_normalize_toc` removes `is_garbage_title` entries *before* the score is computed, so the scorer's garbage penalty (`toc_quality.py:69-70`) can't fire on reconciled TOCs.
  - `toc_quality.py:59-93`: blind to junk, sentences and density (A-TQ-01).
- **Root cause:**
  - The final TOCs score 90–100 raw. HP_2022, KA, HP_2019 and OD are all exactly 100. After the cap, every report reads 85.
  - The only exception is JH at 80: 44 L1s against the limit of 35 cost 20 points.
  - The "keep Phase 4" guard (:236-241) compares two raw scores that are both about 100, so it almost never fires. It fired only for BR, where adding 175 headers pushed L1s or orphans over a deduction.
  - Step 1's "OD 99→85" is the cap, not a real comparison.
- **Explains Step 1:** P5.5-02 and, via the Phase 5.7 gate, P5.7-01.
- **Fix proposal:**
  - Score the reconciled TOC *before* `_normalize_toc`, or have `_normalize_toc` return the drop count and deduct for it.
  - Remove the cap. It was added so that Phase 5.7 could "still fire"; with a content-aware score (A-TQ-01) it isn't needed.
  - Make the guard compare like with like: the reconciled TOC vs Phase 4, both scored before normalisation, with the new scorer.
  - Log the raw score and the deduction breakdown per report, so that the numbers mean something.
- **Risk / effort:** low / S.
- **Confidence:** verified by running (the final-parent scores are in the work log).

#### A-5.5-03 · medium · Duplicate chapter parents: deduplication keys on (exact title, page), so the same chapter from three sources survives
- **Location:**
  - `toc_reconciliation_service.py:714-742` (`_deduplicate_parents`): key = (normalised title, page).
  - :482-500: similarity matching is by whole title.
  - :746-775: `_promote_chapters_to_l1` promotes every Docling chapter header, including banner pages.
- **Root cause.** For OD chapter 3, three entries survive:
  - the printed-contents entry, merged by A-4-01: `Chapter-3 Access to Education Comparative view … 3.1 education`, p.38;
  - the Docling header on the chapter banner page: `Chapter 3 Access to Education`, p.36;
  - the Docling header on the first text page: the same title, p.38.

  Their titles or pages differ, so none is deduplicated.
  - HP_2022: bookmark `5 Chapter 1 HP ATIR` plus Docling `CHAPTER-1 PROFILE OF …`.
  - KA: bookmark `6.Chapter 1-Introduction` plus Docling `Chapter-I`.
  - JH: `Chapter-1 OVERVIEW` plus the merged printed entry.
- **Explains Step 1:** P4-03.
- **Fix proposal:**
  - Deduplicate chapters and annexures by their *number* (normalise roman numerals, "CHAPTER-1", "Chapter I"). Keep one L1 per chapter number: the Phase 4 entry, with the page moved to the earliest body page that is not a banner.
  - Drop Docling chapter headers whose number already exists.
  - Deduplicate numbered sections by number the same way.
  - Most cases also disappear once A-4-01 and A-4-02 are fixed.
- **Risk / effort:** low / S.

#### A-5.5-04 · medium · Heading positions and merged order ignore the page: a y-coordinate from one page is stored for a heading on another, and same-page headings are sorted by level, not position
- **Location:**
  - `toc_reconciliation_service.py:640-670` (`_update_heading_positions`): each Docling header is matched to the *first* TOC entry anywhere in the document with similarity ≥ 0.65. The key uses the TOC entry's page, the value the Docling header's y.
  - :522 and :603: `merged.sort(key=lambda e: (e[2], e[0]))` sorts by (page, **level**).
- **Root cause:**
  1. Generic titles ("Introduction", "Gram Panchayats", "Recommendations", "Audit coverage") match an entry on another page. That entry's position key gets the y-coordinate of a header on a different page, so Agent B's chunking splits that page at the wrong height.
  2. On one page, an L2 entry is always placed before an L3 entry, whatever their vertical order. OD p.35 (physical) prints `2.2.6 Loss of Central assistance…` at y=106 and `Recommendation 2.2` / `2.3` at y=455 / 536. The final TOC orders them Rec 2.2, Rec 2.3, 2.2.6. On p.30, `Recommendation 2.1` (y=73) is placed after `2.2 Financial Management` (y=160), so 2.2.1–2.2.5 get nested under "Recommendation 2.1".
- **Explains Step 1:** part of P7-02 (content under the wrong parent) and the OD example in P5.5-01.
- **Evidence:** a PyMuPDF block scan of OD pp. 30/35/43 against the parent order in `audit/parents/OD_*.txt`.
- **Fix proposal:**
  - Match a Docling header to TOC entries only on the same page (±1 for banners), and store the y under that entry.
  - Carry y for *every* entry: Docling headers have it; for printed and bookmark entries, find the title on its page with `page.search_for`, or read the heuristic position.
  - Sort merged TOCs by (page, y).
- **Risk / effort:** low / S–M.
- **Confidence:** verified by reading, with the OD evidence. The chunking impact belongs to Agent B.

#### A-5.5-05 · low · Minor Phase 5.5 defects
- **Title key collapses entries** (`_merge_medium_quality`, :580-582). The Docling lookup is keyed by title[:30], so later headers with the same 30-character prefix are dropped. Repeated real headings such as "Audit coverage" in PRI and ULB chapters keep only the last.
- **`_prefer_docling_low_quality` replaces the TOC wholesale** (:626) whenever Docling has as many entries or more, discarding a real but short Phase 4 TOC (pre-fix 2020_16: 0→133).
- **The strategy trace is always "unknown".** `main.py:743` reads `scaffold["reconciliation_strategy"]`, which is never set; the method is stored in `toc_method`.
- **`_infer_level_from_docling`** gives L1 to any unnumbered header with bbox height > 25 (:466). A two-line bold sentence becomes a chapter in the merge path (KA medium tier).

### Wired-and-working inventory (Phase 5.5)
| Component / flag | Status | Evidence |
|---|---|---|
| Docling header extraction + bbox text clip (incl. rotation) | Works | 82–333 headers per report |
| `section_header_confidence_threshold` 0.60, `similarity_threshold` 0.65, `min_docling_headers`, `quality_*_threshold` | Read | config |
| Noise filter | Runs; too narrow, and one pattern over-rejects (A-5.5-01, A-5.5-05) | |
| Supplement / merge / replace | Runs; admits non-headings (A-5.5-01) | |
| Chapter promotion | Works, but creates duplicate chapters (A-5.5-03) | |
| `_normalize_toc` | Works; hides garbage from the score (A-5.5-02) | |
| Dedup by (title, page) | Runs; misses cross-source duplicates (A-5.5-03) | |
| "Keep Phase 4" guard | Nearly inert (fired 1/26) | BR only |
| Quality cap at 85 | Makes the score constant (A-5.5-02) | 25/26 = 85 |
| L1-count and orphan warnings | Work (log only; no action taken) | |
| `heading_positions` update | Runs; can cross pages (A-5.5-04) | |

---

## Phase 5.7: LLM TOC validation

### Data flow
`main._phase_llm_toc_validation` (`main.py:768`) checks whether `GOOGLE_CLOUD_PROJECT` is set, and then for each report:
1. `TOCLLMValidator.should_validate` (`toc_llm_validator.py:125`): quality < `llm_validation.quality_threshold` (50) or fewer than 3 entries.
2. If eligible, `validate_toc` (:185):
   - takes the text of the first 15 pages, cut to 8000 chars, plus the first 10 existing entries;
   - makes one Gemini call (`max_output_tokens=2000`, temperature 0);
   - parses a JSON array `[level, title, printed_page]`;
   - converts pages via `_convert_page_numbers` (:371);
   - **replaces the whole TOC** and sets quality to `min(85, max(prev, 70))`.

### Does it run?
**Never.** All four runs log `LLM Validation: 0 validated, N skipped` (18 + 2 + 4 + 1 skipped). The call path has never executed in production.

### Issues

#### A-5.7-01 · medium · The gate can't open: quality is always 80–85 and the threshold is 50
- **Location:** `toc_llm_validator.py:165`; `parsing_config.yaml:153` (`quality_threshold: 50`); fed by A-5.5-02 and A-TQ-01.
- **Root cause:** after Phase 5.5, every score is 85 (capped) or 80 (JH), so `quality < 50` is always false. Even with the cap removed, the current scorer rates the worst TOCs (HP_2022, HP_2019) at 100.
- **Explains Step 1:** P5.7-01.
- **Fix:** gate on the content-aware score (A-TQ-01). The expected triggers are:
  - heuristic-source TOCs;
  - junk ratio above 10%;
  - unverifiable ratio above 20%;
  - duplicate chapter numbers;
  - no printed contents and no trustworthy bookmarks.

  But see A-5.7-02 first: opening the gate today would make things worse.

#### A-5.7-02 · high (latent; would fire once the gate opens) · If Phase 5.7 ran, it would misplace every entry by the front-matter offset and replace the whole TOC with it
- **Location:**
  - `toc_llm_validator.py:371-401` (`_convert_page_numbers`): inverts `scaffold["page_map"]`, which is physical+1 for 23/26 PDFs (A-4-06), otherwise "physical ≈ printed − 1".
  - :250-255: whole-TOC replacement and an invented quality score.
- **Root cause:** the LLM is told, correctly, to return *printed* page numbers. Mapping printed N to physical N−1 ignores the 13–33 pages of front matter.
- **Evidence** (scratch run of `_convert_page_numbers` with the production page map):

  | Report | Printed page 15 → physical, as 5.7 maps it | Where printed page 15 really is |
  |---|---|---|
  | OD | 14 | 38 (printed 40 → 65) |
  | 2025_08 | 14 | 34 (printed 40 → 63) |
  | JH | 14 | printed 40 → 61 |

  Every chapter would start about 20–25 pages early, and all of Agent B's page-bounded parents would be wrong.
- **Other defects in the same call:**
  - `max_output_tokens=2000`. A 60–100-entry state TOC as JSON needs roughly 1500–2500 tokens. If the model spends any tokens thinking, `generate_with_retry` raises "No text: max_output_tokens exhausted" (`gemini_client.py:113-114`) and 5.7 silently does nothing.
  - 8000 chars from 15 pages. The contents page of JH runs over three pages (4–6) after about 3 pages of cover and preface text, so the tail of long contents lists is cut.
  - Only 10 existing entries are shown to the model (`existing_toc[:10]`), and `heading_positions` is not rebuilt after the replacement.
  - `validate_toc` calls `should_validate` a second time, emitting a duplicate trace decision.
- **Fix proposal: redesign Phase 5.7 as a *reviewer* of the deterministic TOC, not a re-extractor.**
  - **Input:**
    - the candidate TOC as numbered rows `id | level | title | physical page | printed page`;
    - the contents-page text (pages `start…contents_end` from `printed_toc_parser`, not the first 8000 chars);
    - for each candidate, the first 200 chars of text at its position.
  - **Output**, using a JSON schema (`response_mime_type="application/json"`, `response_schema`): per id, `keep | drop | relevel(n) | retitle("…")`, plus `missing: [{title, printed_page}]`.
  - **Page mapping:** stays deterministic, using `build_printed_page_map` after A-4-03, for any `missing` entries.
  - **Settings:** `max_output_tokens ≥ 8192` and thinking budget 0 or low.
  - **Gate:** the content-aware score (A-5.7-01).
  - This keeps the LLM out of page arithmetic and makes one bounded call per flagged report.
- **Should it run?** Yes, as a reviewer, for the flagged minority (heuristic TOCs, junk bookmarks, low verification). After A-4-01, A-4-02, A-4-03 and A-5.5-01, most reports should not need it.
- **Risk / effort:** medium / M.
- **Confidence:** verified by running `_convert_page_numbers`. The token-budget failure is inferred from the code and not observed, since the call never ran.

### Wired-and-working inventory (Phase 5.7)
| Component / flag | Status | Evidence |
|---|---|---|
| `llm_validation.enabled`, `model`, `quality_threshold`, `max_input_chars`, `max_pages_to_extract` | Read | config |
| Eligibility gate | Never opens (A-5.7-01) | 0 validated in 4 runs |
| Gemini call / parse / page conversion / TOC replace | Never executed; page conversion wrong (A-5.7-02) | scratch test |
| Parallel runner 5.7 path (`parallel_runner.py:198-202`) | Same logic; production runs with `--workers 1` | |


---

## TOC design, end to end, and choosing a source per tier

### What each source actually gives (`toc_gates.json`, 26 PDFs)

| Tier / type | Printed contents | Bookmarks | Section structure lives in |
|---|---|---|---|
| **Union PA/CA** (2020_16, 2023_11, 2023_19, 2025_08, 2025_38…) | Chapters only (7–13 rows); some list sections (2022_29 41, 2025_20 72, 2025_26 95) | Usually merger junk (score 13–47) | Body headings `N.N Title` → must come from Docling/body |
| **Union FRBM / Accounts** (2024_01, 2025_03/04/16/18) | 7 rows | Real Word bookmarks, 60–181 entries, score 93–95 | Bookmarks |
| **State** (OD, JH) | Full 3-column Title \| Para \| Page, to x.y.z (JH 91 rows) | Merger junk (JH) or none (OD) | Printed contents (after A-4-01) |
| **Local compliance** (BR) | 3-column with roman chapters + appendix table | Junk | Printed contents |
| **Local PA** (KA) | 2-column, excellent (82 rows, 98% verified) | Merger junk that *wins* today | Printed contents |
| **ATIR** (HP_2019, HP_2022) | 3-column, PART-A/B, `N \| P a g e` footers | Junk (HP_2022) or none | Printed contents (after A-4-03) |
| **Scanned** (CG) | Only after OCR | None | OCR'd printed contents |

### Recommended design
1. **Page map first.** Build one `printed_page_map` per report in Phase 4 (A-4-03 + A-4-06): the PDF label, else the printed number, else interpolation, else `None`. Everything else uses it: printed-contents placement, logical pages, and the Phase 5.7 reviewer.
2. **Candidates:**
   - printed contents (A-4-01 parser);
   - bookmarks after the junk filter (A-4-02);
   - the heuristic (A-4-04).

   Each is scored by the content-aware score (A-TQ-01) plus its verification ratio.
3. **Selection (not first-wins):**
   1. Printed contents if they are verified at 0.8 or more and have 5 or more entries.
   2. Else bookmarks, if they pass the junk filter.
   3. Else the heuristic.

   If both printed contents and bookmarks pass and agree on chapters, take the richer one (FRBM/Accounts: bookmarks).
4. **Levels by numbering, not fonts:**
   - chapter number → L1;
   - `x.y` → L2, `x.y.z` → L3;
   - PART-A/B → L1 group above the chapters. Or better, fold them into metadata, because ATIRs have Part A = PRIs and Part B = ULBs;
   - Appendix / Annexure items → L2 under "Appendices".
5. **Phase 5.5 becomes "complete the numbering".** Add numbered sections only when the contents page stops at chapters (union), consistent with the chapter number and in order. Add unnumbered headers only with the style and uniqueness checks (A-5.5-01). Carry y for every entry and sort by (page, y) (A-5.5-04).
6. **Deduplicate by number** for chapters, sections and appendices (A-5.5-03).
7. **Phase 5.7 reviews the result** when the score flags it (A-5.7-02), using keep/drop/relevel per ID. The LLM never does page arithmetic.
8. **Report type / ATIR** is detected once in Phase 1 (A-1-03). The ATIR TOC shape (PART-A/B, 4 fixed chapters) can be a known template for validation.

---

## Step 1 issue coverage

| Step 1 ID | Explained by | Notes |
|---|---|---|
| P1-01 | A-3-01 | |
| P1-02 | A-3-02 | |
| P1-03 | A-1-01 (Phases 1–3 part) | Exit-code and workflow status: Agent C |
| P1-04 | Not in scope | Manifest status and stale output in `main._record_failures_in_manifest` / assembly: Agent C |
| P1-05 | A-1-03 | Includes the unreachable `report_type_profiles` ATIR path |
| P1-06 | A-1-02 | On the VM these were local resolutions (rsync), not downloads |
| P1-07 | A-1-04 | |
| P1-08 | Manifest data (user's). A-1-06 notes how `format_report_no`/Date produce the HP IDs | |
| P4-01 | A-4-01 | Five mechanisms, reproduced |
| P4-02 | A-4-02 | Why JH was rejected and HP_2022/KA accepted |
| P4-03 | A-5.5-03, A-4-01, A-4-02, A-4-04 | |
| P5.5-01 | A-5.5-01 | Precision measured on 6 reports |
| P5.5-02 | A-5.5-02, A-TQ-01 | |
| P5.7-01 | A-5.7-01, A-5.7-02 | |
| P8-03 | A-4-06 | Phase 4 page map; consumers belong to Agent B/C |
| P9-09 (BR) | A-4-01, mechanism 5 | BR appendices parsed as sections |
| P7-02 (part) | A-5.5-04, A-4-01, A-4-04 | The remaining wrong-parent causes are in chunking: Agent B |
| P7-03 (part) | A-5.5-01 | |
| X-01 (garbage-title blind spot) | A-TQ-01 | The preflight check uses the same `is_garbage_title` |
| Review list: "HP_2019 35%, HP_2022 18%" | A-4-03 | |

## Hand-offs
- **Agent C:**
  - `main.py:1269` and `parallel_runner.py:275` call `enrich_document` without `task=`, so `report_type_profiles.detect_report_type` never runs. The profiles `atir`, `state_commercial` and `state_performance` are dead in production (A-1-03).
  - The run exit code and status for failed or empty runs (A-1-01).
  - P1-04 stale output.
  - Whether `scaffolding.toc_rejection_alert_threshold`, `min_toc_quality_score` and `embedded_toc_min_entries` are loaded anywhere (A-4-07).
  - The `reconciliation_strategy` trace key (A-5.5-05).
- **Agent B:**
  - `chunking_service.py:576-577, 620-622, 670` read `page_map` with a physical+1 fallback. After A-4-06 they must handle `None`.
  - Chunk boundaries use `heading_positions`, which can hold a y from another page (A-5.5-04), and the TOC order within a page is by level (A-5.5-04). Both feed P7-02.
  - BR's 639 parents come from Phase 7.5, not 5.5: its 5.5 result was "kept_phase4".
  - `text_extractor.py` applies `ocr_normalizer.normalize_headers` to text. Its `ORDINAL_CORRECTIONS` (`(\d)44 CFC` → `\14th CFC`) rewrites digits in body text as well as headers, which is harmless only if "144 CFC" never occurs legitimately.
- **Main session (Phase 9 deep dive):** the `report_type_profiles.REPORT_PROFILES[*].finding_patterns` used by `finding_extractor` are selected by a report type that is always the manifest's "Report Type" (compliance or performance). ATIR and state profiles never apply (A-1-03).

## Summary (ranked issue list)

| ID | Severity | Title | Location |
|---|---|---|---|
| A-4-01 | high | Printed-contents parser breaks the 3-column (Title \| Para \| Page) layout: para number stays in the title, chapter merges with its first section, centred cells shift by one, headers glued in, appendices become sections | `printed_toc_parser.py:24-38, 98-150` |
| A-4-02 | high | Merger-junk bookmarks pass a shape-only score; bookmarks are tried before the printed contents | `scaffolding_service.py:476-483, 734-825`; `data_contracts.py:58-90`; `parsing_config.yaml:62-68` |
| A-5.5-01 | high | Phase 5.5 adds every unmatched Docling header, with no heading test (recommendation boxes, sentences, table row labels) | `toc_reconciliation_service.py:48-57, 473-526, 566-609` |
| A-TQ-01 | high | TOC quality score is blind to junk, sentences, duplicates and density; the worst TOCs score 100 | `toc_quality.py:31-93` |
| A-3-01 | high | OCR timeout fixed at 600 s kills a finished OCR; the existing output is never reused; PDF/A is slow | `ocr_service.py:113-116, 166-174, 213-228`; `parsing_config.yaml:35-41` |
| A-5.7-02 | high (latent) | Phase 5.7, if it ever ran, would shift every entry by 20–25 pages and replace the TOC; 2000-token cap | `toc_llm_validator.py:185-310, 371-401` |
| A-4-05 | high (latent) | Heuristic TOC error handler raises `AttributeError`, so the whole report fails | `scaffolding_service.py:1108-1110` |
| A-4-06 | medium–high | Page map = PDF labels or physical+1; printed numbers are never used (P8-03) | `scaffolding_service.py:1436-1451` |
| A-5.5-04 | medium | Heading y-positions matched across pages; same-page TOC order sorted by level, not y | `toc_reconciliation_service.py:522, 603, 640-670` |
| A-4-03 | medium | "N \| P a g e" page numbers not recognised; footnote markers read as page numbers (HP verify 18%/35%) | `printed_toc_parser.py:153-172` |
| A-5.5-02 | medium | Reconciled quality capped at 85 and scored after garbage removal, so it is constant; the keep-Phase-4 guard is inert | `toc_reconciliation_service.py:69-70, 229-241, 270-272` |
| A-5.5-03 | medium | Duplicate chapter parents: dedup by (title, page) misses cross-source chapters | `toc_reconciliation_service.py:714-775` |
| A-5.7-01 | medium | Phase 5.7 gate never opens (quality 80–85 vs threshold 50) | `toc_llm_validator.py:165`; `parsing_config.yaml:153` |
| A-1-03 | medium | ATIR never detected; `detect_report_type` reads the wrong keys and is never called | `manifest_ingestion_service.py:151-174, 671-679, 727-729`; `report_type_profiles.py:223-264, 330-340` |
| A-3-02 | medium | OCR module has no logger; failures show "✓"; validation failure ignored | `ocr_service.py:1-8, 141-146, 166-178`; `main.py:507-518` |
| A-1-01 | medium | Empty or missed `--reports` selection and ingestion errors end with exit 0 | `main.py:193-197, 240-249` |
| A-4-04 | medium | Heuristic TOC splits banners into several L1s and accepts table rows | `scaffolding_service.py:1112-1287, 1397-1430` |
| A-1-02 | low | Every manifest row resolved or downloaded sequentially before the filter | `manifest_ingestion_service.py:1062-1066`; `main.py:245` |
| A-1-04 | low | Triage cache keyed by ID only; cached "scanned" task may silently lose its OCR'd PDF | `main.py:399-452, 538-556` |
| A-1-05 | low | Tier taken from the first Government Type value only (latent) | `manifest_ingestion_service.py:291-303` |
| A-1-06 | low | Tenacity retry never fires; partial downloads; "of" check in `format_report_no`; misleading trace; triage image-only gap | `manifest_ingestion_service.py:388, 897-1046` |
| A-4-07 | low | Heuristic scans 100 pages only; hard-coded A4 geometry; config keys unused; bad bookmark targets clamp to 0; rejected_toc.log unbounded | `scaffolding_service.py:76, 986, 1066, 1217` |
| A-5.5-05 | low | Title-prefix key collapse; wholesale Docling replace; "unknown" strategy trace; bbox-height L1 | `toc_reconciliation_service.py:466, 580-582, 626`; `main.py:743` |
| Dead code | — | `toc_table_parser.py` (496 lines, no importer); `excel_analysis.py` | |

**Suggested fix order.** The fixes are interdependent:
1. A-4-03 and A-4-06 (page map).
2. A-4-01 (parser).
3. A-4-02 (source selection).
4. A-TQ-01 (score).
5. A-5.5-01, -03 and -04 (reconciliation).
6. A-5.5-02 (cap).
7. A-5.7-02, then A-5.7-01 (reviewer design, then the gate).

A-3-01, A-3-02, A-4-05 and A-1-03 are independent and small.
